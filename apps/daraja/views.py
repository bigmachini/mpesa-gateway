import logging

import httpx
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shortcodes.models import Shortcode
from .serializers import STKPushSerializer
from .stk import initiate_stk_push, query_stk_status

logger = logging.getLogger(__name__)


class STKPushView(APIView):
    """
    POST /api/v1/daraja/stk-push/
    Initiate an STK Push for one of the authenticated client's shortcodes.
    """

    def post(self, request):
        serializer = STKPushSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            shortcode = Shortcode.objects.get(
                uid=data['shortcode_uid'],
                client=request.user,
                is_active=True,
            )
        except Shortcode.DoesNotExist:
            return Response(
                {'detail': 'Shortcode not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = initiate_stk_push(
                shortcode=shortcode,
                phone=data['phone'],
                amount=data['amount'],
                account_ref=data['account_reference'],
                description=data['description'],
            )
        except httpx.HTTPError as exc:
            logger.error('STK Push HTTP error: %s', exc)
            return Response(
                {'detail': 'Failed to reach Daraja API. Please try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class STKStatusView(APIView):
    """
    GET /api/v1/daraja/stk-push/<checkout_request_id>/
    Query the status of a pending STK Push.
    Requires ?shortcode_uid=<uuid> query param.
    """

    def get(self, request, checkout_request_id):
        shortcode_uid = request.query_params.get('shortcode_uid')
        if not shortcode_uid:
            return Response(
                {'detail': 'shortcode_uid query parameter is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            shortcode = Shortcode.objects.get(
                uid=shortcode_uid,
                client=request.user,
                is_active=True,
            )
        except Shortcode.DoesNotExist:
            return Response(
                {'detail': 'Shortcode not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = query_stk_status(shortcode, checkout_request_id)
        except httpx.HTTPError as exc:
            logger.error('STK status query HTTP error: %s', exc)
            return Response(
                {'detail': 'Failed to reach Daraja API. Please try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(result, status=status.HTTP_200_OK)
