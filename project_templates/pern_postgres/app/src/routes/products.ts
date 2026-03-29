import { Router } from "express";
import { z } from "zod";
import { prisma } from "../db/client";
import { requireAuth } from "../middleware/auth";

const router = Router();

const productSchema = z.object({
  name: z.string().min(1),
  price: z.number().nonnegative(),
});

router.get("/products", async (_req, res, next) => {
  try {
    const products = await prisma.product.findMany({ orderBy: { createdAt: "desc" } });
    return res.json({ items: products });
  } catch (err) {
    return next(err);
  }
});

router.post("/products", requireAuth, async (req, res, next) => {
  try {
    const data = productSchema.parse(req.body);
    const product = await prisma.product.create({ data });
    return res.status(201).json(product);
  } catch (err) {
    return next(err);
  }
});

export default router;
