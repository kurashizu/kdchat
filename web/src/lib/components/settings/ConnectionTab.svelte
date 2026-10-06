<script lang="ts">
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { toast } from "svelte-sonner";
  import * as Alert from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { app, ApiError } from "$lib/app.svelte";
  import { ask } from "$lib/confirm.svelte";
  import { t } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";

  const IPV4 = /^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;
  const NAME = /^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$/;
  const validHost = (h: string) => (/^[\d.]+$/.test(h) ? IPV4.test(h) : NAME.test(h)); // (same rules as the server)
  const validPort = (p: string) => /^\d+$/.test(p) && +p >= 1 && +p <= 65535;

  const c = $derived(app.cfg);
  let oscHost = $state(""), oscPort = $state(""), oscErr = $state("");
  let srvHost = $state(""), srvPort = $state(""), srvErr = $state("");
  let pwCur = $state(""), pwNew = $state(""), pwErr = $state("");
  let lanPick = $state(0);
  let loaded = false;
  $effect(() => {
    if (c && !loaded) {
      loaded = true;
      oscHost = c.osc.host; oscPort = String(c.osc.port);
      srvHost = c.server.listen_host ?? ""; srvPort = String(c.server.listen_port ?? "");
    }
  });
  const urls = $derived<string[]>(c?.network?.urls ?? []);
  const url = $derived(urls[Math.min(lanPick, urls.length - 1)]);
  const msg = (e: unknown) => (e as Error).message;
  const section = "space-y-3 rounded-xl border p-4";

  async function saveOsc(e: Event) {
    e.preventDefault();
    if (!validHost(oscHost.trim())) return (oscErr = t("osc.badHost"));
    if (!validPort(oscPort.trim())) return (oscErr = t("osc.badPort"));
    oscErr = "";
    try {
      app.cfg.osc = await app.put("/osc", { host: oscHost.trim(), port: Number(oscPort) });
      app.health();
      toast.success(t("osc.saved", { target: `${oscHost.trim()}:${oscPort}` }));
    } catch (err) { oscErr = (err as ApiError).status === 400 ? msg(err) : t("common.failed", { msg: msg(err) }); }
  }
  async function resetOsc() {
    try {
      app.cfg.osc = await app.put("/osc", undefined, "DELETE");
      oscHost = app.cfg.osc.host; oscPort = String(app.cfg.osc.port); oscErr = "";
      app.health();
      toast(t("osc.resetDone", { target: `${oscHost}:${oscPort}` }));
    } catch (err) { oscErr = msg(err); }
  }
  async function saveSrv(e: Event) {
    e.preventDefault();
    if (!validHost(srvHost.trim())) return (srvErr = t("srv.badHost"));
    if (!validPort(srvPort.trim())) return (srvErr = t("osc.badPort"));
    srvErr = "";
    try { app.cfg.server = await app.put("/settings/server", { listen_host: srvHost.trim(), listen_port: Number(srvPort) }); toast.success(t("srv.saved")); }
    catch (err) { srvErr = msg(err); }
  }
  async function resetSrv() {
    try { app.cfg.server = await app.put("/settings/server", undefined, "DELETE"); srvHost = app.cfg.server.listen_host ?? ""; srvPort = String(app.cfg.server.listen_port ?? ""); toast(t("srv.saved")); }
    catch (err) { srvErr = msg(err); }
  }
  async function savePw(e: Event) {
    e.preventDefault();
    if (pwNew.length < 4) return (pwErr = t("pw.short"));
    pwErr = "";
    try {
      await app.put("/settings/password", { current_password: pwCur || null, new_password: pwNew });
      pwCur = pwNew = "";
      toast.success(t("pw.setDone"));
      setTimeout(() => location.reload(), 1500); // the browser asks for the new password
    } catch (err) { pwErr = (err as ApiError).status === 403 ? t("pw.wrong") : msg(err); }
  }
  async function removePw() {
    if (!(await ask({ title: t("pw.confirmRemoveTitle"), desc: t("pw.confirmRemove"), action: t("pw.remove") }))) return;
    try {
      app.cfg.password = await app.put("/settings/password", { current_password: pwCur || null, new_password: null });
      pwCur = ""; pwErr = ""; toast(t("pw.removed")); app.loadSettings();
    } catch (err) { pwErr = (err as ApiError).status === 403 ? t("pw.wrong") : msg(err); }
  }
</script>

{#if !c}
  <p class="text-muted-foreground py-6 text-sm">…</p>
{:else}
  <div class="space-y-4">
    <form class={section} onsubmit={saveOsc} novalidate>
      <div>
        <h3 class="text-sm font-semibold">{t("osc.title")}</h3>
        <p class="text-muted-foreground text-xs">{t("osc.current", { target: `${c.osc.host}:${c.osc.port}` })} · {t(`osc.src.${c.osc.source ?? "default"}` as any)}</p>
      </div>
      <div class="grid gap-3 sm:grid-cols-[1fr_8rem]">
        <div class="space-y-1.5">
          <Label for="oscHost">{t("osc.host")}</Label>
          <Input id="oscHost" bind:value={oscHost} placeholder="127.0.0.1" autocomplete="off" autocapitalize="off" spellcheck={false} aria-invalid={!!oscErr} />
          <p class="text-muted-foreground text-xs">{t("osc.hostDesc")}</p>
        </div>
        <div class="space-y-1.5">
          <Label for="oscPort">{t("osc.port")}</Label>
          <Input id="oscPort" bind:value={oscPort} inputmode="numeric" placeholder="9000" aria-invalid={!!oscErr} />
        </div>
      </div>
      {#if oscErr || c.osc.error}<p class="text-destructive text-xs" role="alert">{oscErr || t("osc.unresolved", { msg: c.osc.error })}</p>{/if}
      <p class="text-muted-foreground text-xs">{t("osc.hint")}</p>
      <div class="flex flex-wrap gap-2">
        <Button type="submit" size="sm">{t("common.save")}</Button>
        <Button type="button" size="sm" variant="ghost" title={`${c.osc.default.host}:${c.osc.default.port}`} onclick={resetOsc}><RotateCcw />{t("common.reset")}</Button>
      </div>
    </form>

    <section class={section}>
      <h3 class="text-sm font-semibold">{t("lan.title")}</h3>
      {#if urls.length}
        <div class="flex flex-col gap-4 sm:flex-row sm:items-start">
          <img src={"/api/v1/network/qr.svg?url=" + encodeURIComponent(url)} alt={t("lan.qrAlt", { url })} class="size-36 shrink-0 rounded-lg bg-white p-2" />
          <div class="min-w-0 space-y-2">
            <p class="text-muted-foreground text-xs">{t("lan.scan")}</p>
            <div class="flex flex-col items-start gap-1">
              {#each urls as u, i (u)}
                <button type="button" onclick={() => (lanPick = i)} aria-pressed={u === url}
                  class={cn("rounded-md px-2 py-1 font-mono text-sm break-all", u === url ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted")}>
                  {u.replace(/\/$/, "")}</button>
              {/each}
            </div>
          </div>
        </div>
      {:else}
        <p class="text-muted-foreground text-sm">{t("lan.none", { host: c.network.listen_host })}</p>
      {/if}
      <p class="text-muted-foreground text-xs">{t("lan.hint")}</p>
    </section>

    <form class={section} onsubmit={savePw} novalidate>
      <div>
        <h3 class="text-sm font-semibold">{t("pw.title")}</h3>
        <p class="text-muted-foreground text-xs">{t(!c.password.enabled ? "pw.off" : c.password.source === "env" ? "pw.onEnv" : "pw.onSettings")}</p>
      </div>
      {#if !c.password.enabled && c.network.open_on_lan}
        <Alert.Root class="border-amber-500/40 text-amber-700 dark:text-amber-400">
          <TriangleAlert /><Alert.Description class="text-current">{t("lan.notice")}</Alert.Description>
        </Alert.Root>
      {/if}
      <div class="grid gap-3 sm:grid-cols-2">
        {#if c.password.enabled}
          <div class="space-y-1.5">
            <Label for="pwCur">{t("pw.current")}</Label>
            <Input id="pwCur" type="password" bind:value={pwCur} autocomplete="current-password" />
          </div>
        {/if}
        <div class="space-y-1.5">
          <Label for="pwNew">{t("pw.new")}</Label>
          <Input id="pwNew" type="password" bind:value={pwNew} autocomplete="new-password" aria-invalid={!!pwErr} />
        </div>
      </div>
      {#if pwErr}<p class="text-destructive text-xs" role="alert">{pwErr}</p>{/if}
      <p class="text-muted-foreground text-xs">{t("pw.hint")}</p>
      <div class="flex flex-wrap gap-2">
        <Button type="submit" size="sm">{t(c.password.enabled ? "pw.change" : "pw.set")}</Button>
        {#if c.password.enabled}<Button type="button" size="sm" variant="destructive" onclick={removePw}>{t("pw.remove")}</Button>{/if}
      </div>
    </form>

    <form class={section} onsubmit={saveSrv} novalidate>
      <h3 class="text-sm font-semibold">{t("srv.title")}</h3>
      <div class="grid gap-3 sm:grid-cols-[1fr_8rem]">
        <div class="space-y-1.5">
          <Label for="srvHost">{t("srv.host")}</Label>
          <Input id="srvHost" bind:value={srvHost} placeholder="0.0.0.0" autocomplete="off" autocapitalize="off" spellcheck={false} aria-invalid={!!srvErr} />
          <p class="text-muted-foreground text-xs">{t("srv.hostDesc")}</p>
        </div>
        <div class="space-y-1.5">
          <Label for="srvPort">{t("srv.port")}</Label>
          <Input id="srvPort" bind:value={srvPort} inputmode="numeric" placeholder="5555" aria-invalid={!!srvErr} />
        </div>
      </div>
      {#if srvErr}<p class="text-destructive text-xs" role="alert">{srvErr}</p>{/if}
      <p class={cn("text-xs", c.server.restart_needed ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground")}>
        {c.server.restart_needed ? t("srv.restart") : t("srv.hint")}</p>
      <div class="flex flex-wrap gap-2">
        <Button type="submit" size="sm" variant="outline">{t("common.save")}</Button>
        <Button type="button" size="sm" variant="ghost" onclick={resetSrv}><RotateCcw />{t("common.reset")}</Button>
      </div>
    </form>
  </div>
{/if}
