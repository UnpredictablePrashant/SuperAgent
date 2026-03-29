import dotenv from "dotenv";

dotenv.config();

export const env = {
  port: Number(process.env.AUTH_SERVICE_PORT || 4001),
  jwtSecret: process.env.JWT_SECRET || "change-me",
  databaseUrl: process.env.AUTH_DATABASE_URL || "",
  corsOrigin: process.env.CORS_ORIGIN || "http://localhost:5173",
};
