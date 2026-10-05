import type { Locale } from "@/i18n/config";

const english = {
  title: "Subscription",
  description: "Choose a plan for your workspace.",
  sandbox: "Sandbox",
  current: "Current",
  buy: "Buy",
  buyPlan: "Buy {plan}",
  currentPlan: "Current plan: {plan}",
  loading: "Loading…",
  checkoutOpen: "Checkout open",
  included: "Included now",
  planned: "Planned benefits",
  free: {
    name: "Free",
    description: "Your workspace for saved context and insights.",
    benefits: [
      "Save and organize notes and imported files",
      "Analyze your saved context",
      "Read the sources behind your Flares",
    ],
  },
  pro: {
    name: "Pro",
    description: "More room for your startup’s knowledge.",
    trial: "30-day free trial",
    benefits: [
      "Everything in Free",
      "Additional analysis capacity",
      "Expanded workspace limits",
    ],
  },
  team: {
    name: "Team",
    description: "A shared home for your team’s context.",
    benefits: [
      "Everything in Pro",
      "Team workspace administration",
      "Team access controls",
    ],
  },
  sandboxNote: "Paddle Sandbox only. Your workspace plan updates after the server confirms the subscription.",
  teamUnavailable: "Team checkout is not configured yet. A separate Team price is required.",
  loadingStatus: "Loading Paddle Sandbox Checkout…",
  openStatus: "Complete or close the Paddle checkout to continue.",
  completeStatus: "Sandbox checkout completed. Waiting for server confirmation.",
  checking: "Checking your workspace subscription…",
  ownerOnly: "Only the workspace owner can start a Pro subscription.",
  backendSetup: "Sandbox billing setup is not complete yet. Your existing workspace features remain available.",
  confirming: "Checkout completed. Waiting for the subscription to be confirmed…",
  confirmationDelayed: "Confirmation is taking longer than expected. Check the status before trying checkout again.",
  proConfirmed: "Pro is confirmed for this workspace.",
  freeUnavailable: "Changing back to Free is not available here yet. No subscription change was made.",
  refresh: "Check subscription status",
  billingErrors: {
    auth: "Your subscription could not be verified. Sign in again to check it.",
    configuration: "Sandbox billing is not configured yet. Your existing workspace features remain available.",
    backend: "Your subscription status is unavailable. Please check again before starting checkout.",
  },
  errors: {
    configuration: "Paddle Sandbox is not configured yet. Please try again after setup is complete.",
    "sandbox-only": "Checkout requires a Paddle Sandbox token. Live payments are not enabled.",
    price: "The Pro Sandbox price is missing or invalid. Please contact support.",
    auth: "Please sign in to your Flare account before starting checkout.",
    permission: "Only the workspace owner can start a Pro subscription.",
    backend: "The billing service could not prepare checkout. Check your connection and try again.",
    load: "Paddle could not load. Check your connection, reload this page, and try again.",
    open: "Checkout could not open. Please try again.",
    payment: "Checkout could not complete. Please try again in Paddle Sandbox.",
  },
};

type SubscriptionCopy = {
  [Key in keyof typeof english]: typeof english[Key] extends string
    ? string
    : typeof english[Key] extends { benefits: string[] }
      ? { [Field in keyof typeof english[Key]]: typeof english[Key][Field] extends string[] ? string[] : string }
      : { [Field in keyof typeof english[Key]]: string };
};

const spanish: SubscriptionCopy = {
  title: "Suscripción",
  description: "Elige un plan para tu espacio de trabajo.",
  sandbox: "Sandbox",
  current: "Actual",
  buy: "Comprar",
  buyPlan: "Comprar {plan}",
  currentPlan: "Plan actual: {plan}",
  loading: "Cargando…",
  checkoutOpen: "Pago abierto",
  included: "Incluido ahora",
  planned: "Ventajas previstas",
  free: {
    name: "Free",
    description: "Tu espacio para el contexto guardado y los insights.",
    benefits: [
      "Guardar y organizar notas y archivos importados",
      "Analizar tu contexto guardado",
      "Consultar las fuentes de tus Flares",
    ],
  },
  pro: {
    name: "Pro",
    description: "Más espacio para el conocimiento de tu startup.",
    trial: "Prueba gratuita de 30 días",
    benefits: [
      "Todo lo incluido en Free",
      "Capacidad de análisis adicional",
      "Límites ampliados del espacio de trabajo",
    ],
  },
  team: {
    name: "Team",
    description: "Un lugar compartido para el contexto de tu equipo.",
    benefits: [
      "Todo lo incluido en Pro",
      "Administración del espacio del equipo",
      "Controles de acceso del equipo",
    ],
  },
  sandboxNote: "Solo Paddle Sandbox. El plan de tu espacio se actualiza cuando el servidor confirma la suscripción.",
  teamUnavailable: "El pago de Team aún no está configurado. Se necesita un precio independiente para Team.",
  loadingStatus: "Cargando el pago de Paddle Sandbox…",
  openStatus: "Completa o cierra el pago de Paddle para continuar.",
  completeStatus: "Pago de Sandbox completado. Esperando la confirmación del servidor.",
  checking: "Comprobando la suscripción de tu espacio…",
  ownerOnly: "Solo el propietario del espacio puede iniciar una suscripción Pro.",
  backendSetup: "La configuración de Sandbox aún no está completa. Las funciones actuales de tu espacio siguen disponibles.",
  confirming: "Pago completado. Esperando la confirmación de la suscripción…",
  confirmationDelayed: "La confirmación está tardando más de lo previsto. Comprueba el estado antes de volver a iniciar el pago.",
  proConfirmed: "Pro está confirmado para este espacio.",
  freeUnavailable: "Todavía no se puede cambiar a Free aquí. No se modificó ninguna suscripción.",
  refresh: "Comprobar suscripción",
  billingErrors: {
    auth: "No se pudo verificar tu suscripción. Inicia sesión de nuevo para comprobarla.",
    configuration: "Sandbox aún no está configurado. Las funciones actuales de tu espacio siguen disponibles.",
    backend: "El estado de tu suscripción no está disponible. Compruébalo antes de iniciar el pago.",
  },
  errors: {
    configuration: "Paddle Sandbox aún no está configurado. Inténtalo cuando se complete la configuración.",
    "sandbox-only": "El pago requiere un token de Paddle Sandbox. Los pagos reales no están habilitados.",
    price: "El precio de Pro en Sandbox falta o no es válido. Contacta con soporte.",
    auth: "Inicia sesión en tu cuenta de Flare antes de abrir el pago.",
    permission: "Solo el propietario del espacio puede iniciar una suscripción Pro.",
    backend: "El servicio de facturación no pudo preparar el pago. Comprueba tu conexión e inténtalo de nuevo.",
    load: "No se pudo cargar Paddle. Comprueba tu conexión, recarga esta página e inténtalo de nuevo.",
    open: "No se pudo abrir el pago. Inténtalo de nuevo.",
    payment: "No se pudo completar el pago. Inténtalo de nuevo en Paddle Sandbox.",
  },
};

export const subscriptionCopy: Record<Locale, SubscriptionCopy> = {
  en: english,
  es: spanish,
};
