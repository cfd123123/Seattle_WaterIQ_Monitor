package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.AlertAckRequest;
import com.example.waterbusiness.dto.AlertCloseRequest;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.AlertSpecifications;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
public class AlertService {

    private final AlertEventRepository alertEventRepository;

    public Page<AlertEvent> list(
            Pageable pageable,
            String status,
            LocalDateTime createdFrom,
            LocalDateTime createdTo,
            String severity,
            String pollutionLevel
    ) {
        return alertEventRepository.findAll(
                AlertSpecifications.filtered(status, createdFrom, createdTo, severity, pollutionLevel),
                pageable
        );
    }

    public void acknowledge(Long id, AlertAckRequest body) {
        AlertEvent alert = alertEventRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "告警不存在"));
        if ("ACK".equals(alert.getStatus()) || "CLOSED".equals(alert.getStatus())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "告警已处理");
        }
        alert.setStatus("ACK");
        alert.setAcknowledgedAt(LocalDateTime.now());
        if (body != null) {
            if (body.getAcknowledgedBy() != null && !body.getAcknowledgedBy().isBlank()) {
                alert.setAcknowledgedBy(body.getAcknowledgedBy());
            } else {
                alert.setAcknowledgedBy("anonymous");
            }
            if (body.getRemark() != null) {
                alert.setRemark(truncate(body.getRemark(), 500));
            }
        } else {
            alert.setAcknowledgedBy("anonymous");
        }
        alertEventRepository.save(alert);
    }

    public void close(Long id, AlertCloseRequest body) {
        AlertEvent alert = alertEventRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "告警不存在"));
        if ("CLOSED".equals(alert.getStatus())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "告警已关闭");
        }
        alert.setStatus("CLOSED");
        alert.setClosedAt(LocalDateTime.now());
        if (body != null) {
            if (StringUtils.hasText(body.getClosedBy())) {
                alert.setClosedBy(body.getClosedBy().trim());
            } else {
                alert.setClosedBy("anonymous");
            }
            if (StringUtils.hasText(body.getRemark())) {
                alert.setRemark(mergeRemark(alert.getRemark(), body.getRemark()));
            }
        } else {
            alert.setClosedBy("anonymous");
        }
        alertEventRepository.save(alert);
    }

    private static String mergeRemark(String existing, String closeRemark) {
        String add = truncate(closeRemark.trim(), 400);
        if (!StringUtils.hasText(existing)) {
            return truncate(add, 500);
        }
        return truncate(existing + " | 关闭备注: " + add, 500);
    }

    private static String truncate(String s, int max) {
        if (s.length() <= max) {
            return s;
        }
        return s.substring(0, max - 3) + "...";
    }
}
