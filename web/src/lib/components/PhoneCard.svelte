<script lang="ts">
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import { app } from "$lib/app.svelte";
  import { store } from "$lib/api";
  import { t } from "$lib/i18n.svelte";

  let hidden = $state(store.get("phoneHidden", false));
  const url = $derived<string | undefined>(app.cfg?.network?.urls?.[0]);
</script>

{#if url && !hidden}
  <Card.Root class="gap-0 py-0 max-lg:hidden">
    <Card.Header class="flex flex-row items-center gap-2 border-b px-4 !py-3">
      <Smartphone class="text-muted-foreground size-4" />
      <Card.Title class="text-sm">{t("lan.title")}</Card.Title>
      <Button variant="ghost" size="icon-sm" class="ml-auto" aria-label={t("lan.hide")} title={t("lan.hide")}
        onclick={() => { hidden = true; store.set("phoneHidden", true); }}><X /></Button>
    </Card.Header>
    <Card.Content class="flex items-center gap-4 p-4">
      <img src={"/api/v1/network/qr.svg?url=" + encodeURIComponent(url)} alt={t("lan.qrAlt", { url })} class="size-24 shrink-0 rounded-md bg-white p-1.5" />
      <div class="min-w-0 space-y-1.5">
        <p class="text-muted-foreground text-xs">{t("lan.scan")}</p>
        <a href={url} target="_blank" rel="noopener" class="text-primary block font-mono text-sm break-all hover:underline">{url.replace(/\/$/, "")}</a>
      </div>
    </Card.Content>
  </Card.Root>
{/if}
