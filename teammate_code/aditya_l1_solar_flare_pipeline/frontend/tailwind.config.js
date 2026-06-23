/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Mission-control palette
        space: {
          950: "#070a12",
          900: "#0b101b",
          850: "#0f1626",
          800: "#141d31",
          700: "#1b2740",
          600: "#26344f",
          500: "#36486a",
        },
        sxr: "#3fbdf0",
        hxr: "#f6a04d",
        fcast: "#a98bf5",
        confirmed: "#ff5d6c",
        sxronly: "#3fbdf0",
        hxronly: "#f6a04d",
        good: "#3ddc97",
        warn: "#ffc857",
        danger: "#ff5d6c",
      },
      fontFamily: {
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 30px -12px rgba(0,0,0,0.6)",
        glow: "0 0 24px -6px rgba(63,189,240,0.45)",
      },
      keyframes: {
        pulse_ring: {
          "0%": { boxShadow: "0 0 0 0 rgba(255,93,108,0.55)" },
          "70%": { boxShadow: "0 0 0 12px rgba(255,93,108,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(255,93,108,0)" },
        },
        flash: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        pulsering: "pulse_ring 1.6s infinite",
        flash: "flash 1s ease-in-out 2",
      },
    },
  },
  plugins: [],
};
