import { memo, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ViewerContext } from "./features/vrmViewer/viewerContext";
import { buildUrl } from "./utils/buildUrl";
import { config } from "./utils/config";
import { useVrmStoreContext } from "./features/vrmStore/vrmStoreContext";
import isTauri from "./utils/isTauri";

function VrmRenderer({ chatMode }: { chatMode: boolean }) {
  const { viewer } = useContext(ViewerContext);
  const { getCurrentVrm, vrmList, vrmListAddFile, isLoadingVrmList } =
    useVrmStoreContext();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const didSetupRef = useRef(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadingProgress] = useState("");
  const [loadingError, setLoadingError] = useState(false);
  const isVrmLocal = "local" == config("vrm_save_type");

  // Stable refs for canvas event handlers so they can be removed on cleanup
  const dragOverHandlerRef = useRef<((e: DragEvent) => void) | null>(null);
  const dropHandlerRef = useRef<((e: DragEvent) => void) | null>(null);

  // ---- ResizeObserver (uses parent dimensions) -------------------------------
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const resize = () => {
      viewer.resize();
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    window.addEventListener("resize", resize);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, [viewer]);

  // ---- Cleanup canvas drag/drop listeners on unmount ------------------------
  useEffect(() => {
    return () => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      if (dragOverHandlerRef.current) {
        canvas.removeEventListener("dragover", dragOverHandlerRef.current);
      }
      if (dropHandlerRef.current) {
        canvas.removeEventListener("drop", dropHandlerRef.current);
      }
    };
  }, []);

  // ---- Dispose viewer WebGL resources on unmount ----------------------------
  useEffect(() => {
    return () => {
      viewer.dispose();
      didSetupRef.current = false;
    };
  }, [viewer]);

  // ---- Canvas ref callback: setup WebGL + load VRM --------------------------
  const setCanvasRef = useCallback(
    (canvas: HTMLCanvasElement | null) => {
      canvasRef.current = canvas;

      if (!canvas || didSetupRef.current || (isVrmLocal && isLoadingVrmList)) {
        return;
      }

      didSetupRef.current = true;

      // Async IIFE — avoids the anti-pattern of passing an async function
      // as a Promise executor (which swallows errors and confuses stack traces).
      (async () => {
        try {
          await viewer.setup(canvas);
          viewer.resize();

          const currentVrm = getCurrentVrm();
          if (!currentVrm) {
            setIsLoading(true);
            return;
          }

          await viewer.loadVrm(buildUrl(currentVrm.url), (progress) => {
            console.log(`loading model ${progress}`);
          });
          viewer.resize();

          console.log("vrm loaded");
          setLoadingError(false);
          setIsLoading(false);
        } catch (e) {
          console.error("vrm loading error", e);
          setLoadingError(true);
          setIsLoading(false);
        } finally {
          void isTauri();
        }
      })();

      // Store handlers in refs so we can remove them on cleanup
      const dragOverHandler = (event: DragEvent) => {
        event.preventDefault();
      };
      const dropHandler = (event: DragEvent) => {
        event.preventDefault();

        const files = event.dataTransfer?.files;
        if (!files) {
          return;
        }

        const file = files[0];
        if (!file) {
          return;
        }

        const file_type = file.name.split(".").pop();
        if (file_type === "vrm") {
          vrmListAddFile(file, viewer);
        }
      };

      dragOverHandlerRef.current = dragOverHandler;
      dropHandlerRef.current = dropHandler;

      canvas.addEventListener("dragover", dragOverHandler);
      canvas.addEventListener("drop", dropHandler);
    },
    [getCurrentVrm, isLoadingVrmList, isVrmLocal, viewer, vrmListAddFile],
  );

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      <canvas ref={setCanvasRef} className="block h-full w-full" />
      {isLoading && (
        <div className="absolute left-0 top-0 flex h-full w-full items-center justify-center bg-black bg-opacity-50">
          <div className="text-2xl text-white">{loadingProgress}</div>
        </div>
      )}
      {loadingError && (
        <div className="absolute left-0 top-0 flex h-full w-full items-center justify-center bg-black bg-opacity-50">
          <div className="text-2xl text-white">Error loading VRM model...</div>
        </div>
      )}
    </div>
  );
}

export default memo(VrmRenderer);
