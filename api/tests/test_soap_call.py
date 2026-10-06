"""Exercises app/job_executors.execute_soap_call against a real (if
minimal, hand-written) local SOAP 1.1 document/literal server -- zeep is
a *client* library, so "real, not mocked" here means standing up
something that actually speaks SOAP, not just an HTTP server returning
arbitrary JSON like test_job_executors.py's rest_call tests use.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.job_executors import PermanentJobError, RetryableJobError, execute_soap_call

_WSDL_TEMPLATE = """<?xml version="1.0"?>
<wsdl:definitions name="PingService"
    targetNamespace="http://example.com/ping"
    xmlns:tns="http://example.com/ping"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">

  <wsdl:types>
    <xsd:schema targetNamespace="http://example.com/ping">
      <xsd:element name="PingRequest">
        <xsd:complexType>
          <xsd:sequence>
            <xsd:element name="message" type="xsd:string"/>
          </xsd:sequence>
        </xsd:complexType>
      </xsd:element>
      <xsd:element name="PingResponse">
        <xsd:complexType>
          <xsd:sequence>
            <xsd:element name="reply" type="xsd:string"/>
          </xsd:sequence>
        </xsd:complexType>
      </xsd:element>
    </xsd:schema>
  </wsdl:types>

  <wsdl:message name="PingRequestMessage">
    <wsdl:part name="parameters" element="tns:PingRequest"/>
  </wsdl:message>
  <wsdl:message name="PingResponseMessage">
    <wsdl:part name="parameters" element="tns:PingResponse"/>
  </wsdl:message>

  <wsdl:portType name="PingPortType">
    <wsdl:operation name="Ping">
      <wsdl:input message="tns:PingRequestMessage"/>
      <wsdl:output message="tns:PingResponseMessage"/>
    </wsdl:operation>
  </wsdl:portType>

  <wsdl:binding name="PingBinding" type="tns:PingPortType">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
    <wsdl:operation name="Ping">
      <soap:operation soapAction="http://example.com/ping/Ping"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input>
      <wsdl:output><soap:body use="literal"/></wsdl:output>
    </wsdl:operation>
  </wsdl:binding>

  <wsdl:service name="PingService">
    <wsdl:port name="PingPort" binding="tns:PingBinding">
      <soap:address location="{address}"/>
    </wsdl:port>
  </wsdl:service>
</wsdl:definitions>
"""

_SUCCESS_RESPONSE = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <PingResponse xmlns="http://example.com/ping">
      <reply>pong</reply>
    </PingResponse>
  </soap:Body>
</soap:Envelope>
"""

_FAULT_RESPONSE = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <soap:Fault>
      <faultcode>soap:Server</faultcode>
      <faultstring>Something went wrong</faultstring>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: ARG002
        pass

    def do_GET(self):
        if self.path == "/ping.wsdl":
            body = self.server.wsdl_body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.last_request_body = self.rfile.read(length) if length else b""

        if self.path == "/soap-fault":
            self.send_response(500)
            self.send_header("Content-Type", "text/xml")
            self.end_headers()
            self.wfile.write(_FAULT_RESPONSE.encode("utf-8"))
        elif self.path == "/soap-server-error":
            self.send_response(503)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.end_headers()
            self.wfile.write(_SUCCESS_RESPONSE.encode("utf-8"))


@pytest.fixture
def soap_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    address = f"http://127.0.0.1:{server.server_port}/soap-ok"
    server.wsdl_body = _WSDL_TEMPLATE.format(address=address)
    server.last_request_body = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()


def _wsdl_url(server) -> str:
    return f"http://127.0.0.1:{server.server_port}/ping.wsdl"


def test_execute_soap_call_success(soap_server):
    summary = execute_soap_call(
        {"wsdl_url": _wsdl_url(soap_server), "operation": "Ping", "params": {"message": "hello"}}, job_id="job1"
    )
    assert "Ping" in summary
    assert b"hello" in soap_server.last_request_body


def test_execute_soap_call_fault_is_permanent(soap_server):
    # Point the WSDL's own <soap:address> at the fault-returning path by
    # building a second server instance whose wsdl advertises that path.
    soap_server.wsdl_body = _WSDL_TEMPLATE.format(address=f"http://127.0.0.1:{soap_server.server_port}/soap-fault")
    with pytest.raises(PermanentJobError):
        execute_soap_call({"wsdl_url": _wsdl_url(soap_server), "operation": "Ping", "params": {"message": "x"}}, job_id="job1")


def test_execute_soap_call_transport_error_is_retryable():
    with pytest.raises(RetryableJobError):
        execute_soap_call(
            {"wsdl_url": "http://127.0.0.1:1/ping.wsdl", "operation": "Ping", "params": {"message": "x"}}, job_id="job1"
        )
