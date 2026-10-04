export class DeepLinkInbox {
  #pending = null;

  offer(url) {
    const match = /^sto-field:\/\/project\/([0-9a-f-]+)\/activity\/([0-9a-f-]+)$/i.exec(url ?? '');
    if (match) this.#pending = {project: match[1].toLowerCase(), activity: match[2].toLowerCase()};
  }

  afterConfirmedSync(identity, activities) {
    if (!identity || !this.#pending) return null;
    const hint = this.#pending;
    if (hint.project !== identity.project.toLowerCase()) return null;
    if (!activities.some(row => row.value.toLowerCase() === hint.activity)) return null;
    this.#pending = null;
    return hint.activity;
  }

  clear() { this.#pending = null; }
}
