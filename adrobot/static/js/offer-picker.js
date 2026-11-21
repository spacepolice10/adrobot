function offerPicker() {
  return {
    offerQuery: "",
    offersRequest: 0,
    matches: [],
    selectedOffer: null,
    offerMessage: "",

    formatOfferLabel(offer) {
      return `#${offer.id} · ${offer.name}`;
    },

    setOfferQuery(query) {
      this.offersRequest += 1;
      this.offerQuery = query;
      this.selectedOffer = null;
      this.matches = [];
      this.offerMessage = "";
    },

    selectOffer(offer) {
      this.setOfferQuery(this.formatOfferLabel(offer));
      this.selectedOffer = offer;
    },

    async searchOffers() {
      const query = this.offerQuery.trim();
      if (!query || this.selectedOffer) return;

      const request = ++this.offersRequest;
      this.offerMessage = "Ищем офферы…";
      try {
        const params = new URLSearchParams({ q: query });
        const response = await fetch(`/api/offers/search?${params}`, { cache: "no-store" });
        const offers = await response.json();
        if (request !== this.offersRequest) return;
        if (!response.ok) {
          this.offerMessage = typeof offers.detail === "string"
            ? offers.detail
            : "Не удалось загрузить офферы.";
          return;
        }

        this.matches = offers;
        this.offerMessage = offers.length ? "" : "Офферы не найдены.";
      } catch {
        if (request === this.offersRequest) {
          this.offerMessage = "Не удалось загрузить офферы.";
        }
      }
    },
  };
}
