<script lang="ts">
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import { buttonVariants } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Label } from "$lib/components/ui/label";
  import { confirmState, confirmed } from "$lib/confirm.svelte";
  import { t } from "$lib/i18n.svelte";

  function done(ok: boolean) {
    if (ok) confirmed();
    confirmState.open = false;
    confirmState.resolve?.(ok);
    confirmState.resolve = null;
  }
</script>

<AlertDialog.Root bind:open={confirmState.open} onOpenChange={(o) => { if (!o) done(false); }}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{confirmState.title}</AlertDialog.Title>
      <AlertDialog.Description>{confirmState.desc}</AlertDialog.Description>
    </AlertDialog.Header>
    {#if confirmState.remember}
      <div class="flex items-center gap-2">
        <Checkbox id="confirm-dont-ask" bind:checked={confirmState.dontAsk} />
        <Label for="confirm-dont-ask" class="text-muted-foreground text-sm font-normal">{t("common.dontAsk")}</Label>
      </div>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel onclick={() => done(false)}>{t("common.cancel")}</AlertDialog.Cancel>
      <AlertDialog.Action
        class={confirmState.destructive ? buttonVariants({ variant: "destructive" }) : ""}
        onclick={() => done(true)}>{confirmState.action}</AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
