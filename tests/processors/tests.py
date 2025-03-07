# -*- coding: utf-8 -*-

#  BSD 3-Clause License
#
#  Copyright (c) 2019, Elasticsearch BV
#  All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
#  * Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
#  FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
#  DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#  SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
#  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
#  OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import absolute_import

import logging
import os

import mock
import pytest

import elasticapm
from elasticapm import Client, processors
from elasticapm.conf.constants import BASE_SANITIZE_FIELD_NAMES_UNPROCESSED, ERROR, SPAN, TRANSACTION
from elasticapm.utils import compat
from tests.utils import assert_any_record_contains


@pytest.fixture()
def http_test_data():
    return {
        "context": {
            "request": {
                "body": "foo=bar&password=123456&secret=abc&cc=1234567890098765&custom_field=123",
                "env": {
                    "foo": "bar",
                    "password": "hello",
                    "secret": "hello",
                    "custom_env": "bye",
                },
                "headers": {
                    "foo": "bar",
                    "password": "hello",
                    "secret": "hello",
                    "authorization": "bearer xyz",
                    "some-header": "some-secret-value",
                    "cookie": "foo=bar; baz=foo",
                },
                "cookies": {
                    "foo": "bar",
                    "password": "topsecret",
                    "secret": "topsecret",
                    "sessionid": "123",
                    "custom-sensitive-cookie": "123",
                },
                "url": {
                    "full": "http://example.com/bla?foo=bar&password=123456&secret=abc&cc=1234567890098765&custom_field=123",
                    "search": "foo=bar&password=123456&secret=abc&cc=1234567890098765&custom_field=123",
                },
            },
            "response": {
                "status_code": "200",
                "headers": {
                    "foo": "bar",
                    "password": "hello",
                    "secret": "hello",
                    "authorization": "bearer xyz",
                    "some-header": "some-secret-value",
                    "cookie": "foo=bar; baz=foo",
                },
            },
        }
    }


@pytest.mark.parametrize(
    "elasticapm_client, custom_field",
    [
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["sensitive-stacktrace-val"]},
            processors.MASK,
        ),
        ({}, "bye"),
    ],
    indirect=["elasticapm_client"],
)
def test_stacktrace(elasticapm_client, custom_field):
    data = {
        "exception": {
            "stacktrace": [
                {
                    "vars": {
                        "foo": "bar",
                        "password": "hello",
                        "secret": "hello",
                        "sensitive-stacktrace-val": "bye",
                    }
                }
            ],
            "cause": [
                {
                    "stacktrace": [
                        {
                            "vars": {
                                "foo": "bar",
                                "password": "hello",
                                "secret": "hello",
                                "sensitive-stacktrace-val": "bye",
                            }
                        }
                    ],
                    "cause": [
                        {
                            "stacktrace": [
                                {
                                    "vars": {
                                        "foo": "bar",
                                        "password": "hello",
                                        "secret": "hello",
                                        "sensitive-stacktrace-val": "bye",
                                    }
                                }
                            ]
                        }
                    ],
                }
            ],
        }
    }

    result = processors.sanitize_stacktrace_locals(elasticapm_client, data)

    assert "stacktrace" in result["exception"]
    for stacktrace in (
        result["exception"]["stacktrace"],
        result["exception"]["cause"][0]["stacktrace"],
        result["exception"]["cause"][0]["cause"][0]["stacktrace"],
    ):
        assert len(stacktrace) == 1
        frame = stacktrace[0]
        assert "vars" in frame
        vars = frame["vars"]
        assert "foo" in vars
        assert vars["foo"] == "bar"
        assert "password" in vars
        assert vars["password"] == processors.MASK
        assert "secret" in vars
        assert vars["secret"] == processors.MASK
        assert "sensitive-stacktrace-val" in vars
        assert vars["sensitive-stacktrace-val"] == custom_field


def test_remove_http_request_body(http_test_data):
    assert "body" in http_test_data["context"]["request"]

    result = processors.remove_http_request_body(None, http_test_data)

    assert "body" not in result["context"]["request"]


@pytest.mark.parametrize(
    "elasticapm_client, custom_field, expected_header_cookies",
    [
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["custom-sensitive-cookie"]},
            {"custom-sensitive-cookie": processors.MASK},
            "foo=bar; password={0}; secret={0}; csrftoken={0}; custom-sensitive-cookie={0}".format(processors.MASK),
        ),
        (
            {},
            {"custom-sensitive-cookie": "123"},
            "foo=bar; password={0}; secret={0}; csrftoken={0}; custom-sensitive-cookie=123".format(processors.MASK),
        ),
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["custom-sensitive-*"]},
            {"custom-sensitive-cookie": processors.MASK},
            "foo=bar; password={0}; secret={0}; csrftoken={0}; custom-sensitive-cookie={0}".format(processors.MASK),
        ),
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["custom-sensitive"]},
            {"custom-sensitive-cookie": "123"},
            "foo=bar; password={0}; secret={0}; csrftoken={0}; custom-sensitive-cookie=123".format(processors.MASK),
        ),
    ],
    indirect=["elasticapm_client"],
)
def test_sanitize_http_request_cookies(elasticapm_client, custom_field, expected_header_cookies, http_test_data):
    http_test_data["context"]["request"]["headers"][
        "cookie"
    ] = "foo=bar; password=12345; secret=12345; csrftoken=abc; custom-sensitive-cookie=123"

    result = processors.sanitize_http_request_cookies(elasticapm_client, http_test_data)
    expected = {
        "foo": "bar",
        "password": processors.MASK,
        "secret": processors.MASK,
        "sessionid": processors.MASK,
    }

    expected.update(custom_field)

    assert result["context"]["request"]["cookies"] == expected

    assert result["context"]["request"]["headers"]["cookie"] == expected_header_cookies

    http_test_data["context"]["request"]["headers"].pop("cookie")
    http_test_data["context"]["request"]["headers"][
        "Cookie"
    ] = "foo=bar; password=12345; secret=12345; csrftoken=abc; custom-sensitive-cookie=123"

    result = processors.sanitize_http_request_cookies(elasticapm_client, http_test_data)
    expected = {
        "foo": "bar",
        "password": processors.MASK,
        "secret": processors.MASK,
        "sessionid": processors.MASK,
    }

    expected.update(custom_field)

    assert result["context"]["request"]["cookies"] == expected

    assert result["context"]["request"]["headers"]["Cookie"] == expected_header_cookies


@pytest.mark.parametrize(
    "elasticapm_client, expected_cookies",
    [
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["custom-sensitive-cookie"]},
            "foo=bar; httponly; secure ; sessionid={0}; httponly; secure; custom-sensitive-cookie={0}".format(
                processors.MASK
            ),
        ),
        (
            {},
            "foo=bar; httponly; secure ; sessionid={0}; httponly; secure; custom-sensitive-cookie=123".format(
                processors.MASK
            ),
        ),
    ],
    indirect=["elasticapm_client"],
)
def test_sanitize_http_response_cookies(elasticapm_client, expected_cookies, http_test_data):
    http_test_data["context"]["response"]["headers"][
        "set-cookie"
    ] = "foo=bar; httponly; secure ; sessionid=bar; httponly; secure; custom-sensitive-cookie=123"

    result = processors.sanitize_http_response_cookies(elasticapm_client, http_test_data)

    assert result["context"]["response"]["headers"]["set-cookie"] == expected_cookies


@pytest.mark.parametrize(
    "elasticapm_client, custom_header",
    [
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["some-header"]},
            {"some-header": processors.MASK},
        ),
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["some-*"]},
            {"some-header": processors.MASK},
        ),
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["other-val"]},
            {"some-header": "some-secret-value"},
        ),
        ({"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["*-*"]}, {"some-header": processors.MASK}),
    ],
    indirect=["elasticapm_client"],
)
def test_sanitize_http_headers(elasticapm_client, custom_header, http_test_data):
    result = processors.sanitize_http_headers(elasticapm_client, http_test_data)
    expected = {
        "cookie": "foo=bar; baz=foo",
        "foo": "bar",
        "password": processors.MASK,
        "secret": processors.MASK,
        "authorization": processors.MASK,
    }
    expected.update(custom_header)
    assert result["context"]["request"]["headers"] == expected
    assert result["context"]["response"]["headers"] == expected


@pytest.mark.parametrize(
    "elasticapm_client, custom_env",
    [
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["custom_env"]},
            {"custom_env": processors.MASK},
        ),
        ({}, {"custom_env": "bye"}),
    ],
    indirect=["elasticapm_client"],
)
def test_sanitize_http_wgi_env(elasticapm_client, custom_env, http_test_data):
    result = processors.sanitize_http_wsgi_env(elasticapm_client, http_test_data)
    expected = {
        "foo": "bar",
        "password": processors.MASK,
        "secret": processors.MASK,
    }
    expected.update(custom_env)
    assert result["context"]["request"]["env"] == expected


@pytest.mark.parametrize(
    "elasticapm_client, expected",
    [
        (
            {"sanitize_field_names": BASE_SANITIZE_FIELD_NAMES_UNPROCESSED + ["custom_field"]},
            "foo=bar&password={0}&secret={0}&cc=1234567890098765&custom_field={0}".format(processors.MASK),
        ),
        ({}, "foo=bar&password={0}&secret={0}&cc=1234567890098765&custom_field=123".format(processors.MASK)),
    ],
    indirect=["elasticapm_client"],
)
def test_post_as_string(elasticapm_client, expected, http_test_data):
    result = processors.sanitize_http_request_body(elasticapm_client, http_test_data)
    assert result["context"]["request"]["body"] == expected


def test_sanitize_dict():
    result = processors._sanitize("foo", {1: 2})
    assert result == {1: 2}


def test_non_utf8_encoding(elasticapm_client, http_test_data):
    broken = compat.b("broken=") + u"aéöüa".encode("latin-1")
    http_test_data["context"]["request"]["headers"]["cookie"] = broken
    result = processors.sanitize_http_request_cookies(elasticapm_client, http_test_data)
    assert result["context"]["request"]["headers"]["cookie"] == u"broken=a\ufffd\ufffd\ufffda"


def test_remove_stacktrace_locals():
    data = {"exception": {"stacktrace": [{"vars": {"foo": "bar", "password": "hello", "secret": "hello"}}]}}
    result = processors.remove_stacktrace_locals(None, data)

    assert "stacktrace" in result["exception"]
    stack = result["exception"]["stacktrace"]
    for frame in stack:
        assert "vars" not in frame


@processors.for_events(ERROR, TRANSACTION, SPAN)
def dummy_processor(client, data):
    data["processed"] = True
    return data


@processors.for_events()
def dummy_processor_no_events(client, data):
    data["processed_no_events"] = True
    return data


def dummy_processor_failing(client, data):
    raise ValueError("oops")


@pytest.mark.parametrize(
    "elasticapm_client",
    [{"processors": "tests.processors.tests.dummy_processor,tests.processors.tests.dummy_processor_no_events"}],
    indirect=True,
)
def test_transactions_processing(elasticapm_client):
    for i in range(5):
        elasticapm_client.begin_transaction("dummy")
        with elasticapm.capture_span("bla"):
            pass
        elasticapm_client.end_transaction("dummy_transaction", "success")
    for transaction in elasticapm_client.events[TRANSACTION]:
        assert transaction["processed"] is True
        assert "processed_no_events" not in transaction
    for span in elasticapm_client.events[SPAN]:
        assert span["processed"] is True
        assert "processed_no_events" not in span


@pytest.mark.parametrize(
    "elasticapm_client",
    [{"processors": "tests.processors.tests.dummy_processor,tests.processors.tests.dummy_processor_no_events"}],
    indirect=True,
)
def test_exception_processing(elasticapm_client):
    try:
        1 / 0
    except ZeroDivisionError:
        elasticapm_client.capture_exception()
    assert elasticapm_client.events[ERROR][0]["processed"] is True
    assert "processed_no_events" not in elasticapm_client.events[ERROR][0]


@pytest.mark.parametrize(
    "elasticapm_client",
    [{"processors": "tests.processors.tests.dummy_processor,tests.processors.tests.dummy_processor_no_events"}],
    indirect=True,
)
def test_message_processing(elasticapm_client):
    elasticapm_client.capture_message("foo")
    assert elasticapm_client.events[ERROR][0]["processed"] is True
    assert "processed_no_events" not in elasticapm_client.events[ERROR][0]


@mock.patch("elasticapm.base.constants.HARDCODED_PROCESSORS", ["tests.processors.tests.dummy_processor"])
@pytest.mark.parametrize(
    "elasticapm_client",
    [
        {
            "processors": "tests.processors.tests.dummy_processor,"
            "tests.processors.tests.dummy_processor_no_events,"
            "tests.processors.tests.dummy_processor"
        }
    ],
    indirect=True,
)
def test_deduplicate_processors(elasticapm_client):
    processors = elasticapm_client.load_processors()
    assert len(processors) == 2
    for p in processors:
        assert callable(p)


def test_for_events_decorator():
    @processors.for_events("error", "transaction")
    def foo(client, event):
        return True

    assert foo.event_types == {"error", "transaction"}


def test_drop_events_in_processor(elasticapm_client, caplog):
    dropping_processor = mock.MagicMock(return_value=None, event_types=[TRANSACTION], __name__="dropper")
    shouldnt_be_called_processor = mock.Mock(event_types=[])

    elasticapm_client._transport._processors = [dropping_processor, shouldnt_be_called_processor]
    with caplog.at_level(logging.DEBUG, logger="elasticapm.transport"):
        elasticapm_client.begin_transaction("test")
        elasticapm_client.end_transaction("test", "FAIL")
    assert dropping_processor.call_count == 1
    assert shouldnt_be_called_processor.call_count == 0
    assert elasticapm_client._transport.events[TRANSACTION][0] is None
    assert_any_record_contains(
        caplog.records, "Dropped event of type transaction due to processor mock.mock.dropper", "elasticapm.transport"
    )


@pytest.mark.parametrize(
    "elasticapm_client",
    [{"processors": "tests.processors.tests.dummy_processor,tests.processors.tests.dummy_processor_failing"}],
    indirect=True,
)
def test_drop_events_in_failing_processor(elasticapm_client, caplog):

    with caplog.at_level(logging.WARNING, logger="elasticapm.transport"):
        elasticapm_client.begin_transaction("test")
        elasticapm_client.end_transaction("test", "FAIL")
    assert elasticapm_client._transport.events[TRANSACTION][0] is None
    assert_any_record_contains(
        caplog.records,
        "Dropped event of type transaction due to exception in processor tests.processors.tests.dummy_processor_failing",
        "elasticapm.transport",
    )


def test_context_lines_processor(elasticapm_client):
    abs_path = os.path.join(os.path.dirname(__file__), "..", "utils", "stacks")
    fname1 = os.path.join(abs_path, "linenos.py")
    fname2 = os.path.join(abs_path, "linenos2.py")
    data = {
        "exception": {
            "stacktrace": [
                {"context_metadata": (fname1, 3, 2, None, None)},
                {"context_metadata": (fname2, 5, 2, None, None)},
                {"context_metadata": (fname1, 17, 2, None, None)},
                {"no": "context"},
            ]
        }
    }
    processed = processors.add_context_lines_to_frames(elasticapm_client, data)
    assert processed["exception"]["stacktrace"] == [
        {"pre_context": ["1", "2"], "context_line": "3", "post_context": ["4", "5"]},
        {"pre_context": ["c", "d"], "context_line": "e", "post_context": ["f", "g"]},
        {"pre_context": ["15", "16"], "context_line": "17", "post_context": ["18", "19"]},
        {"no": "context"},
    ]
