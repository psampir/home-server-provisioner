# scripts/

Files dropped here are shipped to every managed host's `/usr/local/bin/`
by the `custom_scripts` role.

Layout:

```
scripts/
├── _common/      # every host
└── <hostname>/   # one specific host (e.g. hsp-app/)
```

Use whatever language you want - the role does not validate shebangs.
The original filename (including suffix) is preserved on the target,
so a file named `nightly-summary.sh` is invoked as `nightly-summary.sh`.

See `roles/custom_scripts/README.md` for the full reference.
