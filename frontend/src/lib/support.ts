const SUPPORT_EMAIL_PATTERN =
  /^[A-Za-z0-9.!#$%&'*+/=_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

export function normalizeSupportEmail(value: string | undefined): string | null {
  const email = value?.trim();
  if (!email || email.length > 254 || !SUPPORT_EMAIL_PATTERN.test(email)) {
    return null;
  }
  return email;
}
