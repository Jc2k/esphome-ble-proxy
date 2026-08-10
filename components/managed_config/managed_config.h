#pragma once

#include "esphome/components/api/api_server.h"
#include "esphome/core/component.h"

namespace esphome::managed_config {

enum class ApiKeyMigrationState : uint8_t {
  NOT_REQUESTED,
  PENDING,
  SUCCEEDED,
  FAILED,
};

class ManagedConfigComponent : public Component {
 public:
  void set_api_encryption_key(api::psk_t key) {
    this->api_encryption_key_ = key;
    this->api_key_migration_state_ = ApiKeyMigrationState::PENDING;
  }

  void loop() override;
  void dump_config() override;

 protected:
  api::psk_t api_encryption_key_{};
  ApiKeyMigrationState api_key_migration_state_{ApiKeyMigrationState::NOT_REQUESTED};
};

}  // namespace esphome::managed_config
