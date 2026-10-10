"use client";

import jsQR from "jsqr";
import { Camera, CameraOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// read a QR code with the tablet's back camera; the code goes to onScan like a scanner's would.
// Browsers open the camera only on HTTPS or localhost: on plain http the button says why.
export function CameraScan({ onScan, disabled }: { onScan: (value: string) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  // read after mount: the server render cannot know how the tablet opened the page
  const [secure, setSecure] = useState(true);
  useEffect(() => setSecure(window.isSecureContext), []);
  return (
    <>
      <Button type="button" variant="outline" className="h-12" disabled={disabled} onClick={() => setOpen(true)} title="Scan the QR code with the camera">
        {secure ? <Camera /> : <CameraOff />} Camera
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Scan with camera</DialogTitle>
            <DialogDescription>Hold the label's QR code inside the frame. It reads by itself.</DialogDescription>
          </DialogHeader>
          {open && !secure && (
            <p role="alert" className="border border-warning/40 bg-warning-soft px-4 py-3 text-sm font-medium text-warning">
              Browsers open the camera only on HTTPS or on this computer at localhost. This page is on plain http. Start the app with <code>make dev-https</code> and open the https address, or type the label code.
            </p>
          )}
          {open && secure && (
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

const CAMERA_ERROR: Record<string, string> = {
  NotAllowedError: "Camera permission was refused. Allow the camera for this site in the browser settings.",
  NotFoundError: "No camera found on this device.",
  NotReadableError: "The camera is busy in another app. Close it and try again.",
};

function Viewfinder({ onRead }: { onRead: (value: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string>();
  // latest callback without restarting the camera when the page re-renders
  const read = useRef(onRead);
  read.current = onRead;

  useEffect(() => {
    let stream: MediaStream | null = null;
    let frame = 0;
    let done = false;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });

    // decode a downscaled frame each animation tick until a code is found
    const tick = () => {
      const v = video.current;
      if (done || !v || !ctx) return;
      if (v.readyState >= v.HAVE_ENOUGH_DATA && v.videoWidth) {
        const scale = Math.min(1, 640 / v.videoWidth);
        canvas.width = Math.round(v.videoWidth * scale);
        canvas.height = Math.round(v.videoHeight * scale);
        ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
        const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
        if (code?.data.trim()) {
          done = true;
          read.current(code.data.trim());
          return;
        }
      }
      frame = requestAnimationFrame(tick);
    };

    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
      .then((s) => {
        stream = s;
        if (done || !video.current) return s.getTracks().forEach((t) => t.stop());
        video.current.srcObject = s;
        return video.current.play().then(() => {
          frame = requestAnimationFrame(tick);
        });
      })
      .catch((e: DOMException) => setError(CAMERA_ERROR[e.name] ?? `Camera did not start: ${e.message}`));
    if (!navigator.mediaDevices) setError("This browser cannot open the camera here. Use HTTPS or localhost.");

    return () => {
      done = true;
      cancelAnimationFrame(frame);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  if (error)
    return (
      <p role="alert" className="border border-danger/40 bg-danger-soft px-4 py-3 text-sm font-medium text-danger">
        {error}
      </p>
    );
  return (
    <div className="relative aspect-square w-full overflow-hidden bg-foreground">
      <video ref={video} muted playsInline className="size-full object-cover" />
      <span className="pointer-events-none absolute inset-[18%] border-2 border-ember" aria-hidden />
    </div>
  );
}
