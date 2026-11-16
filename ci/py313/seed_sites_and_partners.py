#!/usr/bin/env python3
"""Idempotently seed ``django_site`` + ``core_partner`` for the discovery py3 env.

Runs inside the runtime container (repo mounted at ``/workspace``) with
``DJANGO_SETTINGS_MODULE=course_discovery.settings.py313``.

Data-flow rationale (see triboo-doc
``docs/py313/course-discovery-py313-upgrade-2026-11-13.md`` §3.6.1):

* ``django_site.domain`` is the LMS host prefix used by ``refresh_course_metadata``
  (spliced with ``settings.COURSES_API`` URL/OIDC path).
* ``core_partner``'s ``partner`` FK + ``short_code``/``name`` are the org-ownership
  backbone (Course/Organization/Subject/Topic all hang off it).
* ``core_partner`` endpoint fields (``courses_api_url``/``oidc_url_root``/``lms_url``/
  ``studio_url``) are DEAD in this fork — ``refresh_course_metadata`` reads
  ``settings.COURSES_API`` instead — but are seeded here for semantic completeness
  and to support a future restoration of the Partner-driven path.
* OIDC credentials are intentionally NOT stored in ``core_partner`` (the fork does
  not read them there, and they are sensitive); they live in ``settings.COURSES_API``
  (``discovery.auth.json`` in production).

Every value is overridable via environment; the defaults match the local devstack
(``lms:18000`` / ``cms:18010`` container aliases).
"""
import os
import sys
from pathlib import Path

# Make the repo root (which holds the `course_discovery` package) importable
# regardless of where this script is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'course_discovery.settings.py313')

import django
django.setup()

from django.contrib.sites.models import Site
from course_discovery.apps.core.models import Partner

SITE_ID = int(os.environ.get('DISCOVERY_SITE_ID', '1'))
SITE_DOMAIN = os.environ.get('DISCOVERY_SITE_DOMAIN', 'lms:18000')
SITE_NAME = os.environ.get('DISCOVERY_SITE_NAME', 'platform-py3-lms')
PARTNER_NAME = os.environ.get('DISCOVERY_PARTNER_NAME', 'Discovery Py3 Dev')
PARTNER_CODE = os.environ.get('DISCOVERY_PARTNER_CODE', 'discovery-py3')
LMS_URL = os.environ.get('DISCOVERY_LMS_URL', 'http://lms:18000')
STUDIO_URL = os.environ.get('DISCOVERY_STUDIO_URL', 'http://cms:18010')


def main():
    site, _ = Site.objects.update_or_create(
        id=SITE_ID,
        defaults={'domain': SITE_DOMAIN, 'name': SITE_NAME},
    )

    partner, created = Partner.objects.update_or_create(
        site=site,
        defaults={
            'name': PARTNER_NAME,
            'short_code': PARTNER_CODE,
            'courses_api_url': '%s/api/courses/v1/' % LMS_URL,
            'oidc_url_root': '%s/oauth2' % LMS_URL,
            'lms_url': LMS_URL,
            'studio_url': STUDIO_URL,
        },
    )

    print('Site: id=%d domain=%s name=%s' % (site.id, site.domain, site.name))
    print('Partner: %s id=%d name=%r short_code=%r site_id=%d' % (
        'created' if created else 'updated', partner.id, partner.name,
        partner.short_code, partner.site_id,
    ))
    print('  lms_url=%r studio_url=%r courses_api_url=%r oidc_url_root=%r' % (
        partner.lms_url, partner.studio_url, partner.courses_api_url,
        partner.oidc_url_root,
    ))


if __name__ == '__main__':
    main()
