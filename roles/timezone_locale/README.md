# timezone_locale

Sets the system timezone and generates the locales used by the host.

## What it does

1. Installs the `locales` package.
2. Sets the timezone.
3. Generates the primary locale and any extra locales.
4. Writes `LANG=<locale>` to `/etc/default/locale`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `timezone_locale_timezone` | `UTC` | IANA timezone name, for example `Europe/Warsaw` |
| `timezone_locale_locale` | `en_US.UTF-8` | Primary locale and `LANG` value |
| `timezone_locale_extra_locales` | `[]` | Additional locales to generate |

## Notes

- The role writes only `LANG` to `/etc/default/locale`. It does not set
  `LC_ALL`, so per-user or per-service overrides still work.
- Generate a locale before using it in a service environment. The role does
  this for the primary and extra entries.
- Changing the timezone does not rewrite timestamps in existing logs.
  `journalctl` displays them in the current timezone unless `UTC` is
  requested.
