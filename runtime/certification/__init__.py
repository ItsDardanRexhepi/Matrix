"""Professional certification program for The Matrix.

Three certification tracks examine platform development, security
auditing, and enterprise architecture. A passed exam issues a certificate
recorded in the gateway's database. It is not attested on-chain: the record
has an ``eas_uid`` column that nothing fills.
"""

from runtime.certification.assessments import CertificationManager

__all__ = ["CertificationManager"]
