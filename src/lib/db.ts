import { PrismaClient } from "@prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

declare global {
  // eslint-disable-next-line no-var
  var _prisma: PrismaClient | undefined;
}

function getClient(): PrismaClient {
  if (!global._prisma) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) throw new Error("DATABASE_URL non défini");
    const adapter = new PrismaPg({ connectionString });
    global._prisma = new PrismaClient({
      adapter,
      log: process.env.NODE_ENV === "development" ? ["error", "warn"] : ["error"],
    });
  }
  return global._prisma;
}

// Lazy proxy — DB client is only created on first actual query, not at module load time.
// This allows Next.js to build without DATABASE_URL being available at compile time.
export const prisma = new Proxy({} as PrismaClient, {
  get(_target, prop: string | symbol) {
    return (getClient() as any)[prop];
  },
});
