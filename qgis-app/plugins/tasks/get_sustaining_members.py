from celery import shared_task
from celery.utils.log import get_task_logger
import requests
from bs4 import BeautifulSoup
from django.conf import settings
import os

logger = get_task_logger(__name__)

@shared_task
def get_sustaining_members():
    """
    Get the Sustaining members HTML section from the new website
    """
    try:
        url = 'https://qgis.org'
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract the section by the specified class name
        section = soup.select_one('section.section')

        if section:
            html_content = section.prettify().replace("Â¶", "¶")
            template_path = os.path.join(settings.SITE_ROOT, 'templates/flatpages/sustaining_members.html')
            with open(template_path, 'w') as f:
                f.write(html_content)
            logger.info(f"get_sustaining_members: Section saved to {template_path}")
        else:
            logger.info("get_sustaining_members: Section not found")
    except requests.RequestException as e:
        logger.info(f"get_sustaining_members: {e}")