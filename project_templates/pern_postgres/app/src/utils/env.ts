import dotenv from "dotenv";

dotenv.config();

export const env = {
  apiPort: Number(process.env.API_PORT || 3000),
  jwtSecret: process.env.JWT_SECRET || "change-me",
  databaseUrl: process.env.DATABASE_URL || "",
  corsOrigin: process.env.CORS_ORIGIN || "http://localhost:5173",
};
