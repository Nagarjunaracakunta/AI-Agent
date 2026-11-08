# TLS Certificate Renewal

Production certificates are issued by Let's Encrypt and managed by cert-manager in the Kubernetes cluster. Certificates renew automatically 30 days before they expire.

## Alerts

The `CertExpiringSoon` alert fires when a certificate has 14 days or less remaining. If you see it, automatic renewal has already failed at least once, so investigate immediately.

## Error TLS-1042

The error `TLS-1042` means that the ACME challenge failed because the DNS-01 record had not propagated. cert-manager creates a TXT record named `_acme-challenge` and Let's Encrypt could not see it in time.

To fix it:

1. Check that the TXT record exists: `dig TXT _acme-challenge.<domain>`.
2. Wait up to 10 minutes for DNS propagation.
3. Trigger a new attempt:

```
kubectl cert-manager renew <certificate-name> -n prod
```

If the record is missing entirely, check that the DNS provider credentials secret `dns-provider-credentials` has not expired.

## Applying the renewed certificate

After a successful renewal, restart the ingress controller so that it picks up the new certificate:

```
kubectl rollout restart deployment/ingress-nginx -n ingress
```

## Wildcard certificate

The wildcard certificate for `*.acme-internal.com` is not managed by cert-manager. The Security team renews it manually once a year. Contact the Security team if it is within 30 days of expiry.

## Expired certificate in production

A production certificate that has actually expired is a SEV1 incident, because customers will see browser security errors. Follow the Incident Response runbook and renew the certificate as the first priority.
