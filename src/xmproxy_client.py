"""
xmproxy_client.py - JSON-RPC TCP client for xmproxysrv
"""

import json
import socket
import logging

logger = logging.getLogger(__name__)


class XmproxyError(Exception):
    """Exception for xmproxysrv errors"""
    pass


class XmproxyClient:
    """JSON-RPC 2.0 TCP client for xmproxysrv"""

    def __init__(self, host='127.0.0.1', port=40005, timeout=5):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._id_counter = -1

    def _next_id(self):
        """Generate next request ID (starts from 0)"""
        self._id_counter += 1
        return self._id_counter

    def call(self, method, params=None):
        """
        Send JSON-RPC request and receive response.

        The xmproxysrv uses null-terminated strings over TCP, not newlines.

        Args:
            method: RPC method name
            params: Optional parameters dict

        Returns:
            Result dict from response

        Raises:
            XmproxyError: On RPC error or communication failure
        """
        # Build request - only include params if provided
        # Server expects no params field for parameterless calls
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id()
        }
        if params:
            request["params"] = params

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)

        try:
            sock.connect((self.host, self.port))

            # Send request with null terminator (as expected by xmproxysrv)
            request_json = json.dumps(request)
            request_data = request_json.encode('utf-8') + b'\x00'
            sock.sendall(request_data)
            logger.debug(f"Sent: {request_json}")

            # Receive response - server sends null-terminated string
            response_data = b''
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk
                    # Check for null terminator or complete JSON
                    if b'\x00' in response_data:
                        # Remove null terminator
                        response_data = response_data.rstrip(b'\x00')
                        break
                    # Also check if we have a complete JSON object
                    try:
                        json.loads(response_data.decode('utf-8'))
                        break  # Valid JSON received
                    except json.JSONDecodeError:
                        continue  # Keep reading
                except socket.timeout:
                    if response_data:
                        break  # Use what we have
                    raise

            if not response_data:
                raise XmproxyError("Empty response from server")

            # Parse response
            response_str = response_data.decode('utf-8').strip()
            logger.debug(f"Received: {response_str}")

            response = json.loads(response_str)

            # Check for error
            if 'error' in response:
                error = response['error']
                error_msg = error.get('message', str(error))
                raise XmproxyError(f"RPC error: {error_msg}")

            return response.get('result', {})

        except socket.timeout:
            raise XmproxyError("Connection timed out")
        except socket.error as e:
            raise XmproxyError(f"Socket error: {e}")
        except json.JSONDecodeError as e:
            raise XmproxyError(f"Invalid JSON response: {e}")
        finally:
            sock.close()

    def is_connected(self):
        """
        Check if xmproxysrv is reachable on its port.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((self.host, self.port))
            sock.close()
            return True
        except Exception:
            return False

    def get_online_status(self):
        """
        Get XMPP connection status.

        Returns:
            Status string: "online", "offline", "unknown", or "disconnected"
        """
        try:
            result = self.call("get_online_status")
            return result.get("status", "unknown")
        except XmproxyError as e:
            logger.warning(f"Failed to get status: {e}")
            return "disconnected"
        except Exception as e:
            logger.error(f"Unexpected error getting status: {e}")
            return "error"

    def set_online_status(self, status):
        """
        Set XMPP online status.

        Args:
            status: "online" or "offline"

        Returns:
            Result dict
        """
        return self.call("set_online_status", {"status": status})

    def send_message(self, to, msg):
        """
        Send XMPP message.

        Args:
            to: Recipient JID
            msg: Message text

        Returns:
            Result dict
        """
        return self.call("send_message", {"to": to, "msg": msg})

    def get_inbox_count(self):
        """
        Get number of messages in inbox.

        Returns:
            Integer count
        """
        result = self.call("get_inbox_count")
        return result.get("count", 0)

    def get_inbox_message(self, index):
        """
        Get inbox message by index.

        Args:
            index: Message index (0-based)

        Returns:
            Message dict
        """
        return self.call("get_inbox_message", {"index": index})

    def empty_inbox(self):
        """
        Clear all inbox messages.

        Returns:
            Result dict
        """
        return self.call("empty_inbox")

    def shutdown(self):
        """
        Request graceful shutdown of xmproxysrv.

        Returns:
            Result dict or None on failure
        """
        try:
            return self.call("shutdown")
        except XmproxyError as e:
            logger.warning(f"Shutdown request failed: {e}")
            return None
        except Exception:
            return None
