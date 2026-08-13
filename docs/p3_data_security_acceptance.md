# P3 data-security acceptance

Date: 2026-08-13

## Delivered boundary

- New research inputs and generated visualizations are stored in the versioned
  `ra-aes256-gcm-v1` envelope (AES-256-GCM, random 96-bit nonce).
- Key material is derived from the stable desktop installation secret and salt with
  a purpose-separated PBKDF2-HMAC-SHA256 derivation. Raw keys are not stored in SQLite.
- AES-GCM associated data binds artifact ID, owner ID, plaintext SHA-256, and format.
  Reads verify ciphertext SHA-256, the authentication tag, and plaintext SHA-256.
- Upload inspection happens in memory. Persisted summaries contain counts and shape
  metadata, not text/PDF previews, column names, or sample values.
- Analysis and Nextflow inputs use verified temporary plaintext for the operation
  lifetime. The materialized file is deleted on success, failure, cancellation, or
  context exit.
- Authenticated downloads are owner-scoped and return bytes only after integrity
  verification. Failed verification returns HTTP 409 and records a failed audit event.
- Legacy plaintext migration is explicit, scoped to the authenticated owner, capped at
  1,000 records per request, and deletes the plaintext after the encrypted record commits.
- Sensitive events use a globally ordered HMAC-SHA256 chain. The admin endpoint and
  desktop security center report encryption coverage, legacy records, chain head, and
  verification failures.

## Security claims and non-claims

This implementation detects encrypted-file tampering and modification, reordering, or
internal deletion of chained audit rows. It does not claim that a local administrator
cannot extract installation secrets from a running process, nor can a database-only
chain prove that its final rows were not truncated. Institution-grade non-repudiation
requires periodically anchoring the chain head in signed or WORM storage.

The feature is a desktop data-protection control, not HIPAA, GDPR, CSL, or human-genome
compliance certification. Production handling of PHI or controlled genomic data still
requires data classification, export approval, retention/destruction rules, backup-key
rotation and recovery drills, institutional SSO/authorization, and independent review.

## Automated acceptance

`tests/test_data_security.py` verifies:

1. uploaded plaintext does not appear in the stored envelope or persisted summary;
2. a valid owner download returns the original bytes;
3. ciphertext damage blocks download;
4. a second authenticated user cannot read the artifact;
5. researchers cannot access the administrator integrity endpoint;
6. legacy plaintext migrates and the old file is removed;
7. a changed audit row makes chain verification fail.
8. stale temporary plaintext from an unclean exit is purged on recovery.

## Final release evidence

- Python: 246 passed, 0 failed (`238.32s`).
- Vue: 105 modules transformed; hashed assets `index-B_8CywLJ.css` and
  `index-jgGz0vc-.js`.
- Frozen EXE: 38,432,933 bytes; SHA-256
  `A28A63952212EB425C42DEB81C147C64D887F1B3DFCD6A5C7F48C309E70A913F`.
- Frozen security profile:
  `runtime-validation/frozen-p3-security-final-20260813-213631`.
- Frozen checks passed: first-run setup, encrypted envelope, plaintext absence,
  restart decryption, HTTP 409 tamper rejection, valid four-entry audit chain.

The full evidence ledger is in `docs/test_report.md`.
