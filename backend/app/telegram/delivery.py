import logging
from telegram.error import BadRequest

log=logging.getLogger(__name__)

async def send_part(method, part, **kwargs):
    options={'read_timeout':30,'write_timeout':30,'connect_timeout':10,'disable_web_page_preview':True,**kwargs}
    try:
        return await method(text=part.html,parse_mode='HTML',**options)
    except BadRequest as exc:
        if not any(word in str(exc).lower() for word in ('parse entities','entity','unsupported start tag','parse_mode')):
            raise
        log.warning('telegram_format_rejected fallback=clean_plain_text')
        # A rejected parse was not delivered; one plain-text retry is safe.
        return await method(text=part.plain,parse_mode=None,**options)
