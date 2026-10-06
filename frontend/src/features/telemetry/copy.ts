import type { Locale } from "@/i18n/config";
const en = {
  title: "Website analytics",
  description: "Allow anonymous visitor and page counts through Microsoft Application Insights? We don’t send your account identity, saved content, or URL query values.",
  allow: "Allow analytics", reject: "Reject", change: "Change analytics choice",
  allowed: "Analytics allowed for this browser.", rejected: "Optional website analytics is off.",
  unset: "Optional website analytics stays off until you allow it.",
  blocked: "Your browser’s privacy signal keeps optional website analytics off.",
  storageError: "Your choice could not be saved. Analytics stays off in this tab.",
  retention: "Your choice and anonymous visitor cookie expire after 30 days. You can change your choice here at any time.",
  privacy: "Analytics & cookies", cancel: "Keep current choice",
};
type Copy = { [Key in keyof typeof en]: string };
const es: Copy = {
  title: "Analítica del sitio web",
  description: "¿Permites contar visitas y páginas de forma anónima con Microsoft Application Insights? No enviamos tu identidad, contenido guardado ni valores de consulta de las URL.",
  allow: "Permitir analítica", reject: "Rechazar", change: "Cambiar elección de analítica",
  allowed: "La analítica está permitida en este navegador.", rejected: "La analítica opcional está desactivada.",
  unset: "La analítica opcional permanece desactivada hasta que la permitas.",
  blocked: "La señal de privacidad de tu navegador mantiene la analítica opcional desactivada.",
  storageError: "No se pudo guardar tu elección. La analítica sigue desactivada en esta pestaña.",
  retention: "Tu elección y la cookie anónima de visitante caducan en 30 días. Puedes cambiar tu elección aquí en cualquier momento.",
  privacy: "Analítica y cookies", cancel: "Mantener elección actual",
};
export const telemetryCopy: Record<Locale, Copy> = { en, es };
