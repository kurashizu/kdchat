<script lang="ts">
  import ImagePlus from "@lucide/svelte/icons/image-plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import WifiOff from "@lucide/svelte/icons/wifi-off";
  import X from "@lucide/svelte/icons/x";
  import { ModeWatcher } from "mode-watcher";
  import { onMount } from "svelte";
  import * as Alert from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { Toaster } from "$lib/components/ui/sonner";
  import * as Tooltip from "$lib/components/ui/tooltip";
  import AppHeader from "$lib/components/AppHeader.svelte";
  import Composer from "$lib/components/Composer.svelte";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import DisplayPanel from "$lib/components/DisplayPanel.svelte";
  import History from "$lib/components/History.svelte";
  import PhoneCard from "$lib/components/PhoneCard.svelte";
  import SettingsDialog from "$lib/components/settings/SettingsDialog.svelte";
  import { app } from "$lib/app.svelte";
  import { isPicture } from "$lib/decode";
  import { store } from "$lib/api";
  import { t } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";

  const mq = typeof window !== "undefined" ? window.matchMedia("(max-width: 1023px)") : null;
  let phone = $state(mq?.matches ?? false);
  let kb = $state(0); // px of the window the on-screen keyboard covers (iOS: the page does not shrink)
  let composerH = $state(0);
  let drag = $state(0);
  let lanOff = $state(store.get("lanNoticeOff", false));

  const lanNotice = $derived(!!app.cfg?.network?.open_on_lan && !app.cfg?.password?.enabled && !lanOff);

  function viewport() {
    const vv = window.visualViewport;
    kb = vv ? Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)) : 0;
  }

  onMount(() => {
    mq?.addEventListener("change", () => (phone = mq.matches));
    window.visualViewport?.addEventListener("resize", viewport);
    window.visualViewport?.addEventListener("scroll", viewport);
    // #settings or #settings=display: open the settings (a link from the docs / a bookmark)
    const m = location.hash.match(/^#settings(?:=(\w+))?$/);
    if (m) app.openSettings(m[1] ?? "general");
    (async () => {
      await app.loadOutputs();
      app.health();
      app.loadSettings();
      app.loadTr();
      app.refreshHistory();
    })();
    const timers = [
      setInterval(() => app.refreshKd(false), 1000),
      setInterval(() => app.health(), 10000),
      setInterval(() => app.refreshHistory(), 15000),
    ];
    const vis = () => { if (!document.hidden) { app.refreshKd(true); app.refreshHistory(); app.health(); } };
    document.addEventListener("visibilitychange", vis);
    return () => { timers.forEach(clearInterval); document.removeEventListener("visibilitychange", vis); };
  });

  // pictures: paste or drop anywhere
  function onPaste(e: ClipboardEvent) {
    const item = [...(e.clipboardData?.items ?? [])].find((i) => i.kind === "file" && (i.type.startsWith("image/") || i.type === ""));
    if (!item) return;
    e.preventDefault();
    app.sendImage(item.getAsFile());
  }
  const hasFiles = (e: DragEvent) => [...(e.dataTransfer?.types ?? [])].includes("Files");
</script>

<svelte:window onpaste={onPaste} onpagehide={() => app.leaving()}
  ondragenter={(e) => { if (hasFiles(e)) drag++; }}
  ondragleave={() => { drag = Math.max(0, drag - 1); }}
  ondragover={(e) => e.preventDefault()}
  ondrop={(e) => { e.preventDefault(); drag = 0; app.sendImage([...(e.dataTransfer?.files ?? [])].find((f) => isPicture(f))); }} />

<ModeWatcher defaultMode="dark" />
<Toaster position={phone ? "top-center" : "bottom-right"} richColors closeButton />
<ConfirmDialog />
<SettingsDialog />

<Tooltip.Provider delayDuration={300}>
  <div class="bg-background text-foreground min-h-dvh">
    <AppHeader />

    {#if app.conn === "bad"}
      <div class="mx-auto max-w-6xl px-3 pt-3 sm:px-4">
        <Alert.Root variant="destructive"><WifiOff /><Alert.Title>{t("conn.banner")}</Alert.Title></Alert.Root>
      </div>
    {/if}
    {#if lanNotice}
      <div class="mx-auto max-w-6xl px-3 pt-3 sm:px-4">
        <Alert.Root class="border-amber-500/40 text-amber-700 dark:text-amber-400">
          <TriangleAlert />
          <Alert.Title class="text-current">{t("lan.notice")}</Alert.Title>
          <Alert.Action class="flex gap-1">
            <Button size="xs" variant="outline" onclick={() => app.openSettings("connection")}>{t("lan.setPw")}</Button>
            <Button size="icon-xs" variant="ghost" aria-label={t("lan.dismiss")} title={t("lan.dismiss")}
              onclick={() => { lanOff = true; store.set("lanNoticeOff", true); }}><X /></Button>
          </Alert.Action>
        </Alert.Root>
      </div>
    {/if}

    <main class="mx-auto grid max-w-6xl gap-4 px-3 py-4 sm:px-4 lg:grid-cols-[minmax(0,1fr)_25rem] lg:items-start"
      style={phone ? `padding-bottom: ${composerH + 16}px` : ""}>
      <div class="flex min-w-0 flex-col gap-4">
        {#if !phone}<Composer {phone} />{/if}
        <History />
      </div>
      <aside class="flex flex-col gap-4 max-lg:order-first lg:sticky lg:top-18">
        <DisplayPanel {phone} />
        <PhoneCard />
      </aside>
    </main>

    {#if phone}
      <div bind:clientHeight={composerH} class="bg-background/95 fixed inset-x-0 z-20 border-t p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] backdrop-blur"
        style={`bottom: ${kb}px`}>
        <Composer {phone} />
      </div>
    {/if}
  </div>
</Tooltip.Provider>

<div class={cn("pointer-events-none fixed inset-3 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-background/80 backdrop-blur-sm transition-opacity",
  drag ? "opacity-100" : "opacity-0")} aria-hidden={!drag}>
  <p class="flex items-center gap-2 text-lg font-medium"><ImagePlus class="text-primary size-6" />{t("kd.drop")}</p>
</div>
