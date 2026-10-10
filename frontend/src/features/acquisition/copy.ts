import type { Locale } from "@/i18n/config";
const en = {
  title: "Help us understand which links work",
  description: "Allow Flare to connect the campaign label on this link with your registration and use of Flare? We use it to compare our X accounts. Saved notes and full link addresses are excluded.",
  allow: "Allow link measurement", reject: "No thanks", details: "What we measure",
  allowed: "Link measurement is allowed for this tab.",
  rejected: "Optional link measurement is off in this tab.",
  unset: "Link measurement stays off until you allow it.",
  blocked: "Your browser’s privacy signal keeps link measurement off.",
  error: "Could not save your choice. Link measurement stays off.",
  withdrawalError: "Could not finish removing measurement data. Please retry.",
  removed: "Your account’s measurement data has been removed and future measurement is off.",
  withdraw: "Turn off account measurement", busy: "Saving…",
  retention: "The optional link cookie lasts up to 7 days. Linked measurement stays for up to 90 days. Change your choice in Settings or the measurement notice.",
  account: "Remove your account’s campaign link and measurement history, and stop future measurement. Your notes, Flares and account stay available. This does not change website page-count analytics.",
};
type Copy = { [Key in keyof typeof en]: string };
const es: Copy = {
  title: "Ayúdanos a saber qué enlaces funcionan",
  description: "¿Permites que Flare vincule la etiqueta de campaña de este enlace con tu registro y uso de Flare? La usamos para comparar nuestras cuentas de X. No incluimos notas guardadas ni direcciones completas de enlaces.",
  allow: "Permitir medición de enlaces", reject: "No, gracias", details: "Qué medimos",
  allowed: "La medición de enlaces está permitida en esta pestaña.",
  rejected: "La medición opcional de enlaces está desactivada en esta pestaña.",
  unset: "La medición de enlaces permanece desactivada hasta que la permitas.",
  blocked: "La señal de privacidad de tu navegador desactiva la medición de enlaces.",
  error: "No se pudo guardar tu elección. La medición sigue desactivada.",
  withdrawalError: "No se pudieron eliminar todos los datos de medición. Inténtalo de nuevo.",
  removed: "Se eliminaron los datos de medición de tu cuenta y se desactivó la medición futura.",
  withdraw: "Desactivar medición de la cuenta", busy: "Guardando…",
  retention: "La cookie opcional del enlace dura hasta 7 días. La medición vinculada dura hasta 90 días. Cambia tu elección en Configuración o en el aviso de medición.",
  account: "Elimina el vínculo de campaña y el historial de medición de tu cuenta y detén la medición futura. Tus notas, Flares y cuenta siguen disponibles. Esto no cambia la analítica de páginas del sitio web.",
};
export const acquisitionCopy: Record<Locale, Copy> = { en, es };
