import smtplib
import logging
import os
import io
import email
import asyncio
import json
import itertools
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formatdate
from email import encoders
import aiohttp
import boto3
from aiohttp import web
from sns_message_validator import (
    InvalidMessageTypeException,
    InvalidCertURLException,
    InvalidSignatureVersionException,
    SignatureVerificationFailureException,
    SNSMessageType,
    SNSMessageValidator
)

routes = web.RouteTableDef()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('proxy')

sns_message_validator = SNSMessageValidator()

relay_lock = asyncio.Lock()

def s3_recv():
    s3 = boto3.client('s3')
    response = s3.list_objects_v2(
        Bucket=os.environ.get('S3_BUCKET_NAME')
    )
    for o in response.get('Contents') or []:
        with io.BytesIO() as f:
            s3.download_fileobj(
                os.environ.get('S3_BUCKET_NAME'),
                o.get('Key'), f
            )
            f.seek(0)
            msg = email.message_from_binary_file(f)
            from_addr = msg.get('From')
            for to_addrs in email.utils.getaddresses(
                filter(None, itertools.chain(
                    msg.get_all('to', []),
                    msg.get_all('cc', []),
                    msg.get_all('bcc', [])
                ))
            ):
                with smtplib.SMTP(
                    os.environ.get('SMTP_HOST'), 
                    os.environ.get('SMTP_PORT')
                ) as s:
                    try:
                        if os.environ.get('SMTP_USER', None):
                            s.login(
                                os.environ.get('SMTP_USER'), 
                                os.environ.get('SMTP_PASSWORD')
                            )
                        s.sendmail(from_addr, to_addrs, msg.as_bytes())
                    except smtplib.SMTPException as e:
                        logger.error(e)

                        fwd = MIMEMultipart()
                        fwd['From'] = os.environ.get('POSTMASTER_MAILBOX')
                        fwd['To'] = os.environ.get('POSTMASTER_MAILBOX')
                        fwd['Date'] = formatdate(localtime=True)
                        fwd['Subject'] = f'Message delivery failure from {from_addr}'
                        fwd.attach(MIMEText(str(e)))

                        part = MIMEBase('application', "octet-stream")
                        part.set_payload(msg.as_bytes())
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition', 
                            f'attachment; filename={msg["Subject"]}.eml'
                        )
                        fwd.attach(part)

                        s.docmd('RSET')
                        s.sendmail(
                            os.environ.get('POSTMASTER_MAILBOX'),
                            os.environ.get('POSTMASTER_MAILBOX'),
                            fwd.as_bytes()
                        )
            s3.delete_object(
                Bucket=os.environ.get('S3_BUCKET_NAME'),
                Key=o.get('Key')
            )

@routes.post('/')
async def relay(request):
    message_type = request.headers.get('x-amz-sns-message-type')
    try:
        sns_message_validator.validate_message_type(message_type)
    except InvalidMessageTypeException as e:
        logger.error(e)
        raise web.HTTPBadRequest(text='Invalid message type.')

    try:
        message = await request.json()
    except json.decoder.JSONDecodeError as e:
        logger.error(e)
        raise web.HTTPBadRequest(text='Request body is not in json format.')

    try:
        sns_message_validator.validate_message(message=message)
    except InvalidCertURLException as e:
        logger.error(e)
        raise web.HTTPBadRequest(text='Invalid certificate URL.')
    except InvalidSignatureVersionException as e:
        logger.error(e)
        raise web.HTTPBadRequest(text='Unexpected signature version.')
    except SignatureVerificationFailureException as e:
        logger.error(e)
        raise web.HTTPBadRequest(text='Failed to verify signature.')

    if message_type == SNSMessageType.SubscriptionConfirmation.value:
        async with aiohttp.ClientSession() as session:
            async with session.get(message.get('SubscribeURL')) as resp:
                if resp.status != 200:
                    logger.error(resp)
                    raise web.HTTPInternalServerError(text='Request to SubscribeURL failed.')
        return web.Response(text='Subscription is successfully confirmed.')

    if message_type == SNSMessageType.UnsubscribeConfirmation.value:
        async with aiohttp.ClientSession() as session:
            async with session.get(message.get('UnsubscribeURL')) as resp:
                if resp.status != 200:
                    logger.error(resp)
                    raise web.HTTPInternalServerError(text='Request to UnsubscribeURL failed.')
        return web.Response(text='Successfully unsubscribed.')

    if message_type == SNSMessageType.Notification.value:
        loop = asyncio.get_running_loop()
        await relay_lock.acquire()
        await loop.run_in_executor(None, s3_recv)
        relay_lock.release()
        return web.Response(status=200)

if __name__ == '__main__':
    app = web.Application()
    app.add_routes(routes)
    s3_recv()
    web.run_app(app)