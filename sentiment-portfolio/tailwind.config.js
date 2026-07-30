/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        body: ["'Inter'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
      colors: {
        base: {
          950: "#0a0e12",
          900: "#0f1419",
          800: "#161c23",
          700: "#1f2730",
          600: "#2b3540",
          500: "#3d4a57",
          400: "#5b6b78",
          300: "#8b98a3",
          200: "#c2ccd3",
          100: "#e8ecef",
          50: "#f5f7f8",
        },
        signal: {
          up: "#ffb648",
          upDim: "#8a5f28",
          down: "#ff5470",
          downDim: "#7a2f3c",
        },
        wash: "#f7f4ee",
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.5)",
      },
      keyframes: {
        tick: {
          "0%": { opacity: "0.4" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        tick: "tick 0.4s ease-out",
      },
    },
  },
  plugins: [
    function ({ addVariant }) {
      addVariant("light", "html.light &");
    },
  ],
};
