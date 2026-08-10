#include "managed_config.h"

#include "esphome/core/log.h"

namespace esphome::managed_config {

static const char *const TAG = "managed_config";

void ManagedConfigComponent::loop() {
  if (this->api_key_migration_state_ != ApiKeyMigrationState::PENDING)
    return;

  if (api::global_api_server == nullptr ||
      !api::global_api_server->save_noise_psk(this->api_encryption_key_, false)) {
    this->api_key_migration_state_ = ApiKeyMigrationState::FAILED;
    ESP_LOGE(TAG, "Failed to persist the API encryption key");
    this->mark_failed();
    return;
  }

  api::global_api_server->set_noise_psk(this->api_encryption_key_);
  this->api_key_migration_state_ = ApiKeyMigrationState::SUCCEEDED;
  ESP_LOGI(TAG, "API encryption key persisted for credential-free updates");
}

void ManagedConfigComponent::dump_config() {
  const char *migration_state;
  switch (this->api_key_migration_state_) {
    case ApiKeyMigrationState::PENDING:
      migration_state = "pending";
      break;
    case ApiKeyMigrationState::SUCCEEDED:
      migration_state = "succeeded";
      break;
    case ApiKeyMigrationState::FAILED:
      migration_state = "failed";
      break;
    case ApiKeyMigrationState::NOT_REQUESTED:
    default:
      migration_state = "not requested";
      break;
  }

  ESP_LOGCONFIG(TAG, "Managed configuration:");
  ESP_LOGCONFIG(TAG, "  API key migration: %s", migration_state);
}

}  // namespace esphome::managed_config
