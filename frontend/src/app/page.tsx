"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { roleHome, useMe } from "@/lib/auth";

// "/" sends each role to its own home
export default function Home() {
  const me = useMe();
  const router = useRouter();
  useEffect(() => {
    if (me.data) router.replace(roleHome(me.data.role));
    if (me.isError) router.replace("/login");
  }, [me.data, me.isError, router]);
  return (
    <div className="grid min-h-dvh place-items-center">
      <Skeleton className="h-8 w-48" />
    </div>
  );
}
