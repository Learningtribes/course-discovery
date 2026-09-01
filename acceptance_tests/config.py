import os

COURSE_ID = os.environ.get('COURSE_ID', 'edX/DemoX')
COURSE_RUN_ID = os.environ.get('COURSE_RUN_ID', 'course-v1:edX+DemoX+Demo_Course')

MARKETING_SITE_URL_ROOT = os.environ.get('MARKETING_SITE_URL_ROOT', 'https://stage.edx.org')
LMS_URL_ROOT = os.environ.get('LMS_URL_ROOT', 'https://courses.stage.edx.org')
ECOMMERCE_URL_ROOT = os.environ.get('ECOMMERCE_URL_ROOT', 'https://ecommerce.stage.edx.org')

BASIC_AUTH_USERNAME = os.environ.get('BASIC_AUTH_USERNAME', '')
BASIC_AUTH_PASSWORD = os.environ.get('BASIC_AUTH_PASSWORD', '')

AFFILIATE_COOKIE_NAME = os.environ.get('AFFILIATE_COOKIE_NAME', 'stage.edx.affiliate_id')
COOKIE_DOMAIN = os.environ.get('COOKIE_DOMAIN', '.edx.org')
