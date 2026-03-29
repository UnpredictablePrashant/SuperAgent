import express from "express";
import cors from "cors";
import helmet from "helmet";
import morgan from "morgan";
import { env } from "./utils/env";
import healthRouter from "./routes/health";
import authRouter from "./routes/auth";
import { errorHandler } from "./middleware/error";

const app = express();

app.use(helmet());
app.use(cors({ origin: env.corsOrigin }));
app.use(express.json());
app.use(morgan("dev"));

app.use("/api", healthRouter);
app.use("/api", authRouter);

app.use(errorHandler);

app.listen(env.port, () => {
  // eslint-disable-next-line no-console
  console.log(`Auth service listening on http://localhost:${env.port}`);
});
