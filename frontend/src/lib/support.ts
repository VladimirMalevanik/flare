export const DEFAULT_SUPPORT_EMAIL = "support@flare4u.tech";

const SUPPORT_EMAIL_PATTERN =
  /^[A-Za-z0-9.!#$%&'*+/=_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

export function normalizeSupportEmail(value: string | undefined): string {
  const email = value?.trim();
  if (!email || email.length > 254 || !SUPPORT_EMAIL_PATTERN.test(email)) {
    return DEFAULT_SUPPORT_EMAIL;
  }
  return email;
}

export function supportMailto(subject: string, email = DEFAULT_SUPPORT_EMAIL): string {
  return `mailto:${email}?subject=${encodeURIComponent(subject)}`;
}
