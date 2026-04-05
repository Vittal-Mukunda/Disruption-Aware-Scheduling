/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background:            "#F8FAFC",
        foreground:            "#0F172A",
        primary:               "#1E3A8A",
        "primary-foreground":  "#EFF6FF",
        secondary:             "#374151",
        "secondary-foreground":"#FFFFFF",
        accent:                "#BFDBFE",
        "accent-foreground":   "#1E40AF",
        muted:                 "#F1F5F9",
        "muted-foreground":    "#6B7280",
        border:                "#CBD5E1",
        destructive:           "#DC2626",
      },
      fontFamily: {
        heading: ['"Fraunces"', 'serif'],
        body:    ['"Nunito"', 'sans-serif'],
      },
      boxShadow: {
        soft:  '0 4px 20px -2px rgba(30,58,138,0.10)',
        float: '0 10px 40px -10px rgba(30,58,138,0.16)',
      },
    },
  },
  plugins: [],
}
