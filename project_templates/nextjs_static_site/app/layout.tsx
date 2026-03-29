import "./globals.css";

export const metadata = {
  title: "Static Next.js Site",
  description: "A clean Next.js static website template.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
