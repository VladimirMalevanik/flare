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
  sandboxNote: "Test purchases use Paddle Sandbox. Your current plan and access stay unchanged.",
  teamUnavailable: "Team checkout is not configured yet. A separate Team price is required.",
  loadingStatus: "Loading Paddle Sandbox Checkout…",
  openStatus: "Complete or close the Paddle checkout to continue.",
  completeStatus: "Sandbox checkout completed. Your plan is still Free; paid access is not enabled yet.",
  errors: {
    configuration: "Paddle Sandbox is not configured yet. Please try again after setup is complete.",
    "sandbox-only": "Checkout requires a Paddle Sandbox token. Live payments are not enabled.",
    price: "The Pro Sandbox price is missing or invalid. Please contact support.",
    auth: "Please sign in to your Flare account before starting checkout.",
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
  sandboxNote: "Las compras de prueba usan Paddle Sandbox. Tu plan actual y tus permisos no cambian.",
  teamUnavailable: "El pago de Team aún no está configurado. Se necesita un precio independiente para Team.",
  loadingStatus: "Cargando el pago de Paddle Sandbox…",
  openStatus: "Completa o cierra el pago de Paddle para continuar.",
  completeStatus: "Pago de Sandbox completado. Tu plan sigue siendo Free; el acceso de pago aún no está habilitado.",
  errors: {
    configuration: "Paddle Sandbox aún no está configurado. Inténtalo cuando se complete la configuración.",
    "sandbox-only": "El pago requiere un token de Paddle Sandbox. Los pagos reales no están habilitados.",
    price: "El precio de Pro en Sandbox falta o no es válido. Contacta con soporte.",
    auth: "Inicia sesión en tu cuenta de Flare antes de abrir el pago.",
    load: "No se pudo cargar Paddle. Comprueba tu conexión, recarga esta página e inténtalo de nuevo.",
    open: "No se pudo abrir el pago. Inténtalo de nuevo.",
    payment: "No se pudo completar el pago. Inténtalo de nuevo en Paddle Sandbox.",
  },
};

export const subscriptionCopy: Record<Locale, SubscriptionCopy> = {
  en: english,
  es: spanish,
};
