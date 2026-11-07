/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Layer accent colors
        layer: {
          blue: { bg: "#eff6ff", border: "#bfdbfe", text: "#1e40af" },
          green: { bg: "#f0fdf4", border: "#bbf7d0", text: "#166534" },
          slate: { bg: "#f8fafc", border: "#cbd5e1", text: "#334155" },
          purple: { bg: "#faf5ff", border: "#ead3fc", text: "#7e22ce" },
          amber: { bg: "#fffbeb", border: "#fcd34d", text: "#92400e" },
          teal: { bg: "#f0fdfa", border: "#99f6e4", text: "#0f766e" },
        },
        // Near-black dark theme
        dark: {
          bg: "#0a0a0b",
          surface: "#141417",
          surfaceLift: "#1e1e22",
          border: "#27272a",
          text: "#fafafa",
          muted: "#a1a1aa",
        },
      },
      borderRadius: {
        card: "0.75rem",
        pill: "9999px",
      },
      animation: {
        "pulse-glow": "pulse-glow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "flow-edge": "flow-edge 1.5s linear infinite",
      },
      keyframes: {
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(168, 85, 247, 0.4)" },
          "50%": { boxShadow: "0 0 0 4px rgba(168, 85, 247, 0)" },
        },
        "flow-edge": {
          "0%": { strokeDasharray: "1000", strokeDashoffset: "1000" },
          "100%": { strokeDasharray: "1000", strokeDashoffset: "0" },
        },
      },
    },
  },
  plugins: [],
}