// ISO 3166-1 alpha-2 codes from the IANA time zone database (iso3166.tab).
const COUNTRY_CODES = [
  "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT",
  "AU", "AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI",
  "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY",
  "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
  "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
  "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK",
  "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
  "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
  "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR",
  "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
  "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS",
  "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
  "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW",
  "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
  "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
  "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
  "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM",
  "SN", "SO", "SR", "SS", "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF",
  "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR", "TT", "TV", "TW",
  "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
  "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW"
];

function countryPicker() {
  const normalize = (text) => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

    const names = new Intl.DisplayNames(["ru"], { type: "region" });
    const englishNames = new Intl.DisplayNames(["en"], { type: "region" });
    const countries = COUNTRY_CODES.map((code) => {
      const name = names.of(code);
      const flag = String.fromCodePoint(
        ...[...code].map((letter) => 0x1F1E6 + letter.charCodeAt(0) - 65),
      );

      return {
        code,
        name,
        label: `${flag} ${name} · ${code}`,
        searchNames: [normalize(name), normalize(englishNames.of(code))],
      };
    }).sort((left, right) => left.name.localeCompare(right.name, "ru"));

  return {
    countryQuery: "",
    countryCode: "",
    countryMatches: [],

    filterCountries() {
      const query = normalize(this.countryQuery.trim());
      if (!query || this.countryCode) return [];

      const exact = countries.find((country) => country.code.toLowerCase() === query);
      const matches = countries.filter(
        (country) => country !== exact && (
          country.code.toLowerCase().startsWith(query) ||
          country.searchNames.some((name) => name.includes(query))
        ),
      );
      return (exact ? [exact, ...matches] : matches).slice(0, 10);
    },

    setCountryQuery(query) {
      this.countryQuery = query;
      this.countryCode = "";
      this.countryMatches = this.filterCountries();
    },

    selectCountry(country) {
      this.countryQuery = country.label;
      this.countryCode = country.code;
      this.countryMatches = [];
    },
  };
}
