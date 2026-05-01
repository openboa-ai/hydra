import Config

config :phoenix, :json_library, Jason

config :hydra_elixir, SymphonyElixirWeb.Endpoint,
  adapter: Bandit.PhoenixAdapter,
  url: [host: "localhost"],
  render_errors: [
    formats: [html: SymphonyElixirWeb.ErrorHTML, json: SymphonyElixirWeb.ErrorJSON],
    layout: false
  ],
  pubsub_server: SymphonyElixir.PubSub,
  live_view: [signing_salt: "hydra-live-view"],
  secret_key_base: String.duplicate("s", 64),
  check_origin: false,
  server: false
