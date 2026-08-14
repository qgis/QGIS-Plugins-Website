# Custom middleware to handle HTTP_AUTHORIZATION
# Author: A. Pasotti

import base64
import binascii
import logging

from django.contrib import auth

logger = logging.getLogger(__name__)

# rpc4django is mounted at /plugins/RPC2/ (see plugins/urls.py). Basic auth is
# only honoured there.
RPC_PATH = "/plugins/RPC2"


def HttpAuthMiddleware(get_response):
    """HTTP-Basic auth for the XML-RPC endpoint.

    The QGIS plugin uploader authenticates each RPC call with Basic
    credentials. This is deliberately narrow:

    * it only applies to the RPC endpoint. It used to run on every URL in the
      site, which turned every page into an unmetered password oracle.
    * it sets request.user without calling auth.login(). RPC clients
      authenticate per call and ignore cookies, so issuing a session would
      write a session row per call and hand out a cookie nobody uses.
    * a malformed header is logged and ignored. Decoding whatever followed the
      scheme unguarded meant any request carrying, say, "Authorization: Token
      x" raised binascii.Error and returned a 500.

    Failed attempts are logged so credential guessing is visible; throttling
    them is a separate concern and is not done here.
    """

    def middleware(request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")

        if request.path.startswith(RPC_PATH) and auth_header.startswith("Basic "):
            remote_addr = request.META.get("REMOTE_ADDR", "")
            try:
                decoded = base64.b64decode(auth_header[6:].strip(), validate=True)
                username, separator, password = decoded.decode("utf8").partition(":")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                logger.warning("Malformed Basic auth header from %s", remote_addr)
            else:
                if not separator:
                    logger.warning(
                        "Basic auth header without a password separator from %s",
                        remote_addr,
                    )
                else:
                    user = auth.authenticate(username=username, password=password)
                    if user:
                        request.user = user
                    else:
                        logger.warning(
                            "Failed Basic auth for username %r from %s",
                            username,
                            remote_addr,
                        )

        return get_response(request)

    return middleware
