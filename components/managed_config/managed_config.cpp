#include "managed_config.h"

#include "esphome/core/log.h"

namespace esphome::managed_config {

static const char *const TAG = "managed_config";

void ManagedConfigComponent::loop() {
  if (!this->persist_api_encryption_key_)
    return;

  this->persist_api_encryption_key_ = false;
  if (api::global_api_server == nullptr ||
      !api::global_api_server->save_noise_psk(this->api_encryption_key_, false)) {
    ESP_LOGE(TAG, "Failed to persist the API encryption key");
    this->mark_failed();
    return;
  }

  api::global_api_server->set_noise_psk(this->api_encryption_key_);
  ESP_LOGI(TAG, "API encryption key persisted for credential-free updates");
}

void ManagedConfigComponent::dump_config() {
  ESP_LOGCONFIG(TAG, "Managed configuration:");
  ESP_LOGCONFIG(TAG, "  API key migration: %s", this->persist_api_encryption_key_ ? "pending" : "not requested");
}

}  // namespace esphome::managed_config
