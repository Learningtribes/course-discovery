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
