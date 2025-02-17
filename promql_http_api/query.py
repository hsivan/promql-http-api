# SPDX-FileCopyrightText: Copyright (c) 2022 NVIDIA CORPORATION & AFFILIATES.
# SPDX-FileCopyrightText: All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from datetime import datetime
from datetime import timezone
import logging
from pandas import DataFrame, Timestamp
from .api_endpoint import ApiEndpoint
import pytz
from typing import Optional


class Base(ApiEndpoint):
    '''
    Base class for Query and QueryRange endpoints
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.timezone = timezone.utc
        self.time_format = "%Y-%m-%dT%H:%M:%S"
        self.schema = None
        self.prom_results = {}

    def to_dataframe(self) -> DataFrame:
        '''
        Convert the PromQL query results to a Pandas DataFrame
        Implicitly executes the query if it has not already been executed

        Parameters:
            None
        Returns:
            df (DataFrame): The query results as a Pandas DataFrame
        '''
        data = self.response.data()
        if data is None:
            raise ValueError("No data in PromQL query response")

        self.prom_results = data['result']
        if len(self.prom_results) == 0:
            raise ValueError("PromQL query response has no results")
        self.logger.debug(f'prom_results: {self.prom_results}')

        if self.schema:
            self.timezone = self.schema.get('timezone', pytz.timezone('UTC'))

        prom_result_type = data['resultType']
        if prom_result_type == 'vector':
            return self._vector_to_dataframe()
        elif prom_result_type == 'matrix':
            return self._matrix_to_dataframe()
        else:
            raise ValueError(f"Unexpected PromQL result type: {prom_result_type}")

    def _vector_to_dataframe(self) -> DataFrame:
        records = []
        columns = self.get_schema_columns()
        df_has_datetime = (self.schema and 'timezone' in self.schema.keys())
        for result in self.prom_results:
            prom_metric = result['metric']
            columns = columns if columns else list(prom_metric.keys())
            record = [prom_metric[column] for column in columns]
            value = result['value']
            full_record = self._make_full_record(value, record, df_has_datetime)
            records.append(full_record)
        if df_has_datetime:
            columns = ['timestamp'] + columns + ['value']
        else:
            columns = ['timestamp', 'datetime'] + columns + ['value']
        df = DataFrame(records, columns=columns)
        return df

    def _matrix_to_dataframe(self):
        records = []
        columns = self.get_schema_columns()
        df_has_datetime = (self.schema and 'timezone' in self.schema.keys())
        for result in self.prom_results:
            prom_metric = result['metric']
            columns = columns if columns else list(prom_metric.keys())
            record = [prom_metric[column] for column in columns]
            values = result['values']
            for value in values:
                full_record = self._make_full_record(value, record, df_has_datetime)
                records.append(full_record)
        if df_has_datetime:
            columns = ['timestamp', 'datetime'] + columns + ['value']
        else:
            columns = ['timestamp'] + columns + ['value']
        df = DataFrame(records, columns=columns)
        return df

    def _make_full_record(self, value, partial_record, df_has_datetime):
        full_record = []
        timestamp = value[0]
        result = self.cast(value[1])
        if df_has_datetime:
            pd_timestamp = Timestamp(timestamp, unit='s', tz=self.timezone)
            full_record = [timestamp, pd_timestamp] + partial_record + [result]
        else:
            full_record = [timestamp] + partial_record + [result]

        self.logger.debug(f'record = {full_record}')
        return full_record

    def get_schema_columns(self) -> 'list[str]':
        if self.schema:
            return self.schema.get('columns', [])
        else:
            return []

    def cast(self, result):
        if self.schema:
            dtype = self.schema.get('dtype', str)
            result = dtype(result)
        return result


class Query(Base):
    '''
    Query API endpoint class
    '''

    def __init__(self,
                 url: str = "",
                 query: str = "",
                 time: datetime = datetime.now()):
        super().__init__(url)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.debug(f"url = {url}; query = {query}; time = {time}")
        self.query = query
        self.time = time

    def __str__(self):
        return self.query

    def __repr__(self):
        return self.query

    def make_url(self):
        '''
        Make the URL for the API endpoint

        Parameters:
            None
        Returns:
            url (str): The URL for the API endpoint
        '''
        url = '/api/v1/query?query=' + str(self.query)
        if self.time:
            time_str = str(self.time.timestamp())
            url += '&time=' + time_str
        return url

    def to_dataframe(self, schema: Optional[dict] = None, authorization_token: str = ""):
        if self.query is None:
            return None
        self.schema = schema
        self.__call__(authorization_token=authorization_token)
        return super().to_dataframe()


class QueryRange(Base):
    '''
    QueryRange API endpoint class
    '''

    def __init__(self,
                 url: str,
                 query: str,
                 start: datetime,
                 end: datetime,
                 step: str):
        super().__init__(url)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.debug(f'query = {query}; start = {start}; end = {end}; step = {step}')
        self.query = query
        self.start = start
        self.end = end
        self.step = step

    def __str__(self):
        return self.query

    def __repr__(self):
        return self.query

    def make_url(self):
        '''
        Make the URL for the API endpoint

        Parameters:
            None
        Returns:
            url (str): The URL for the API endpoint
        '''
        start = str(self.start.timestamp())
        end = str(self.end.timestamp())
        url = '/api/v1/query_range?query=' + self.query
        url += '&start=' + start
        url += '&end=' + end
        url += '&step=' + self.step
        self.logger.debug(f'returned url = {url}')
        return url

    def to_dataframe(self, schema: dict = {}, authorization_token: str = "") -> DataFrame:
        if self.query is None:
            raise ValueError("Please set the QueryRange::query element to issue a PromQL HTTP API query")
        self.schema = schema
        self.__call__(authorization_token=authorization_token)
        return super().to_dataframe()
