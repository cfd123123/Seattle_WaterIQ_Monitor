package com.example.waterbusiness.service;

import feign.FeignException;
import feign.Request;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CopilotServiceTest {

  @Test
  void mapFeignException_shouldMapUpstream500ToBadGateway() {
    FeignException ex = feignException(500, "Internal Server Error");

    ResponseStatusException mapped = CopilotService.mapFeignException(ex);

    assertEquals(HttpStatus.BAD_GATEWAY, mapped.getStatusCode());
    assertEquals("AI copilot unavailable (LLM request failed).", mapped.getReason());
  }

  @Test
  void mapFeignException_shouldMap422ToBadRequest() {
    FeignException ex = feignException(422, "validation error");

    ResponseStatusException mapped = CopilotService.mapFeignException(ex);

    assertEquals(HttpStatus.BAD_REQUEST, mapped.getStatusCode());
    assertEquals("Invalid copilot request.", mapped.getReason());
  }

  @Test
  void mapFeignException_shouldMap503ToServiceUnavailable() {
    FeignException ex = feignException(503, "assistant disabled");

    ResponseStatusException mapped = CopilotService.mapFeignException(ex);

    assertEquals(HttpStatus.SERVICE_UNAVAILABLE, mapped.getStatusCode());
    assertEquals(
        "AI copilot unavailable (assistant disabled or not configured).", mapped.getReason());
  }

  private static FeignException feignException(int status, String body) {
    Request request =
        Request.create(
            Request.HttpMethod.POST,
            "http://localhost:8000/copilot/chat",
            Collections.emptyMap(),
            null,
            StandardCharsets.UTF_8,
            null);
    return FeignException.errorStatus("copilotChat", feignResponse(status, body, request));
  }

  private static feign.Response feignResponse(int status, String body, Request request) {
    return feign.Response.builder()
        .status(status)
        .reason("error")
        .request(request)
        .body(body, StandardCharsets.UTF_8)
        .headers(Collections.emptyMap())
        .build();
  }
}
