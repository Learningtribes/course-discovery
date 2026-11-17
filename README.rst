Course Discovery Service  |Travis|_ |Codecov|_
==============================================
.. |Travis| image:: https://travis-ci.org/edx/course-discovery.svg?branch=master
.. _Travis: https://travis-ci.org/edx/course-discovery

.. |Codecov| image:: http://codecov.io/github/edx/course-discovery/coverage.svg?branch=master
.. _Codecov: http://codecov.io/github/edx/course-discovery?branch=master

Service providing access to consolidated course and program metadata.

Python 3.13 / Django 5.2 Upgrade
--------------------------------

This repository is being migrated from Python 3.5 / Django 1.11 to **Python 3.13 /
Django 5.2**. The upgrade plan, dependency conflict resolutions, phase-by-phase
checklist, acceptance matrix, and environment setup guide (including the
``django_site`` / ``core_partner`` mapping required to fetch course data from the
LMS) are maintained in the Triboo documentation repository:

- `course-discovery Python 3.13 / Django 5.2 upgrade plan <https://github.com/Learningtribes/triboo-doc/blob/py3-discovery/docs/py313/course-discovery-py313-upgrade-2026-11-13.md>`_ (Chinese)

The upgrade work lives on the ``py3-master`` branch. See §3.6.1 of the plan for how
``refresh_course_metadata`` obtains its connection parameters (``settings.COURSES_API``,
loaded from ``discovery.auth.json`` in production) and how the ``core_partner`` table
provides the org-to-partner ownership mapping.

Running and building this service (py3.13)
------------------------------------------

This service no longer has its own orchestration entry point. Its lifecycle is owned by the
Devstack py3.13 replay, which manages it as an optional run sidecar — one container on the
run's network, reusing that run's MySQL (its own database) and memcached. Pass
``DISCOVERY_REPO`` when creating the run and the whole lifecycle follows automatically::

    # build the runtime image (the only manual step)
    cd <devstack>
    make py313-build-discovery DISCOVERY_REPO=<this checkout>

    # create and bring up the run with discovery
    make py313-dev-up RUN_ID=dev313 LMS_PORT=18000 CMS_PORT=18010 \
      PLATFORM_REPO=<platform-worktree> THEME_REPO=<theme> \
      DISCOVERY_REPO=<this checkout> DISCOVERY_IMAGE=ltdps/discovery:py313-local \
      DISCOVERY_PORT=18381

    # day-to-day
    make py313-start / py313-stop / py313-restart / py313-status
    make py313-shell-discovery / py313-status-discovery / py313-update-db-discovery

The complete command reference — every course-discovery py3.13 command, with its project
location, function and usage, plus the retired Python 2 commands that must not be used — is
`Appendix B of the upgrade plan
<https://github.com/Learningtribes/triboo-doc/blob/py3-discovery/docs/py313/course-discovery-py313-upgrade-2026-11-13.md#appendix-b--command-reference-all-course-discovery-py313-commands>`_:
B.1 Devstack lifecycle targets, B.2 discovery-specific targets, B.3 the replay phase
dispatcher, B.4 the platform-side OAuth2 application seed, B.5 commands in this repository
(``ci/py313/build-runtime-image.py``, ``ci/py313/seed_sites_and_partners.py``,
``ci/py313/run_tests_mysql.sh``), B.6 the settings that steer the LMS integration, B.7 retired
commands, and B.8 the first-time ordering from an empty host.

``ci/py313/README.md`` in this repository covers the same ground for the image and the
site/partner seed contract.

Documentation
-------------

`Documentation <https://edx-discovery.readthedocs.io/en/latest/>`_ is hosted on Read the Docs. The source is hosted in this repo's `docs <https://github.com/edx/course-discovery/tree/master/docs>`_ directory. The docs are automatically rebuilt and redeployed when commits are merged to master. To contribute, please open a PR against this repo.

License
-------

The code in this repository is licensed under version 3 of the AGPL unless otherwise noted. Please see the LICENSE_ file for details.

.. _LICENSE: https://github.com/edx/course-discovery/blob/master/LICENSE

How To Contribute
-----------------

Contributions are welcome. Please read `How To Contribute <https://github.com/edx/edx-platform/blob/master/CONTRIBUTING.rst>`_ for details. Even though it was written with ``edx-platform`` in mind, these guidelines should be followed for Open edX code in general.

Development
-----------

Is the build failing because translations are out of date?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Run ``make check_translations_up_to_date`` and check in the generated *.mo & *.po files to your PR.


Reporting Security Issues
-------------------------

Please do not report security issues in public. Please email security@edx.org.

Get Help
--------

Ask questions and discuss this project on `Slack <https://openedx.slack.com/messages/general/>`_ or in the `edx-code Google Group <https://groups.google.com/forum/#!forum/edx-code>`_.
