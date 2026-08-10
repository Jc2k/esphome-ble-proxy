#pragma once

#include "esphome/components/api/api_server.h"
#include "esphome/core/component.h"

namespace esphome::managed_config {

class ManagedConfigComponent : public Component {
 public:
  void set_api_encryption_key(api::psk_t key) {
    this->api_encryption_key_ = key;
    this->persist_api_encryption_key_ = true;
  }

  void loop() override;
  void dump_config() override;

 protected:
  api::psk_t api_encryption_key_{};
  bool persist_api_encryption_key_{false};
};

}  // namespace esphome::managed_config
