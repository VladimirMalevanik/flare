import { createSandboxCheckoutClient } from "./checkout-controller";

// NEXT_PUBLIC_* values are public and compiled into the Next.js browser bundle.
// Never add a Paddle API key or webhook secret here.
export const paddleSandboxCheckout = createSandboxCheckoutClient({
  token: process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN,
  proPriceId: process.env.NEXT_PUBLIC_PADDLE_PRO_PRICE_ID,
  initialize: async (options) => {
    const { initializePaddle } = await import("@paddle/paddle-js");
    return initializePaddle(options);
  },
  getTheme: () => document.documentElement.dataset.theme === "dark" ? "dark" : "light",
});
