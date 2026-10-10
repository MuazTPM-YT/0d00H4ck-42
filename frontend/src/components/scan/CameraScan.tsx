"use client";

import { Camera, CameraOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type Detector = { detect: (src: CanvasImageSource) => Promise<{ rawValue: string }[]> };
type DetectorCtor = new (opts: { formats: string[] }) => Detector;

// read one QR code from the camera; the browser's own reader where it has one (Android, Mac,
// ChromeOS), jsQR otherwise (Windows). Frames are sampled ~7 times a second at 640 px wide.
export function CameraScan({ onScan, label = "Scan with camera", disabled, className }: { onScan: (value: string) => void; label?: string; disabled?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button type="button" variant="outline" disabled={disabled} onClick={() => setOpen(true)} className={className} aria-label={label} title={label}>
        <Camera /> Camera
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{label}</DialogTitle>
            <DialogDescription>Hold the QR label inside the square. It reads on its own.</DialogDescription>
          </DialogHeader>
          {open && (
            <Viewfinder
              onRead={(v) => {
                setOpen(false);
                onScan(v);
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function Viewfinder({ onRead }: { onRead: (value: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  // the parent re-renders often; keep the camera running across those
  const read = useRef(onRead);
  read.current = onRead;

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer = 0;
    let stopped = false;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });

    async function start() {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setError("The camera needs HTTPS or localhost. Open the app at http://localhost:3000 on this machine, or type the code.");
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false });
      } catch (e) {
        const name = (e as DOMException).name;
        setError(name === "NotAllowedError" ? "Camera access was blocked. Allow it in the browser's address bar, then try again." : name === "NotFoundError" ? "No camera found on this device." : "Could not start the camera.");
        return;
      }
      if (stopped || !video.current) return stream.getTracks().forEach((t) => t.stop());
      video.current.srcObject = stream;
      await video.current.play().catch(() => {});
      setReady(true);

      const Native = (window as unknown as { BarcodeDetector?: DetectorCtor }).BarcodeDetector;
      const native = Native ? new Native({ formats: ["qr_code"] }) : null;
      const jsQR = native ? null : (await import("jsqr")).default;

      const tick = async () => {
        if (stopped) return;
        const v = video.current;
        if (v && v.readyState >= 2 && ctx) {
          const w = 640;
          const h = Math.round((v.videoHeight / v.videoWidth) * w) || 480;
          canvas.width = w;
          canvas.height = h;
          ctx.drawImage(v, 0, 0, w, h);
          let text: string | undefined;
          if (native) text = (await native.detect(canvas).catch(() => []))[0]?.rawValue;
          else if (jsQR) text = jsQR(ctx.getImageData(0, 0, w, h).data, w, h, { inversionAttempts: "dontInvert" })?.data;
          if (text && !stopped) {
            stopped = true;
            read.current(text.trim());
            return;
          }
        }
        timer = window.setTimeout(tick, 140);
      };
      tick();
    }
    start();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  if (error)
    return (
      <div className="flex items-start gap-3 border border-danger/40 bg-danger-soft p-4 text-sm text-danger">
        <CameraOff className="mt-0.5 size-5 shrink-0" aria-hidden />
        {error}
      </div>
    );

  return (
    <div className="relative aspect-[4/3] overflow-hidden border border-foreground bg-foreground">
      <video ref={video} muted playsInline className="h-full w-full object-cover" />
      {/* the square to aim at, with ember corners */}
      <div className="pointer-events-none absolute inset-0 grid place-items-center" aria-hidden>
        <div className={cn("relative size-[58%] max-h-[80%] transition-opacity", ready ? "opacity-100" : "opacity-0")}>
          {["top-0 left-0 border-t-2 border-l-2", "top-0 right-0 border-t-2 border-r-2", "bottom-0 left-0 border-b-2 border-l-2", "right-0 bottom-0 border-r-2 border-b-2"].map((c) => (
            <span key={c} className={cn("absolute size-8 border-ember", c)} />
          ))}
        </div>
      </div>
      {!ready && <p className="label absolute inset-0 grid place-items-center text-background">Starting camera…</p>}
    </div>
  );
}
